#!/usr/bin/env python3
"""Create autonomous chemicals for rdkit.mols not covered by source records.

The resulting chemicals have null PubChem/DSSTox identity fields.  Their
structure, Mol, and fingerprints come from the legacy RDKit row.  The audited
migration map is completed, but ORD references are deliberately untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil

import psycopg2


DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
MIN_FREE_BYTES = 5 * 1024**3
EXPECTED_MOLS = 1_435_401
EXPECTED_UNMATCHED = 109_890


def connect():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='absorb_unmatched_rdkit_mols'")
        cur.execute("SET statement_timeout=0")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET work_mem='256MB'")
        cur.execute("SET maintenance_work_mem='256MB'")
        cur.execute("SET synchronous_commit=off")
    conn.commit()
    return conn


def require_space(stage: str) -> None:
    available = shutil.disk_usage("/").free
    if available < MIN_FREE_BYTES:
        raise RuntimeError(
            f"{stage}: only {available / 1024**3:.2f} GiB free; "
            f"hard floor is {MIN_FREE_BYTES / 1024**3:.2f} GiB"
        )


def exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
    return bool(cur.fetchone()[0])


def ensure_meta(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pubchem.rdkit_mol_absorption_meta (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            status text NOT NULL,
            unmatched_before bigint,
            distinct_structures bigint,
            inserted_chemicals bigint,
            mapped_mols bigint,
            first_chemical_id integer,
            last_chemical_id integer,
            started_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz
        )
        """
    )


def build(rebuild_stage: bool) -> None:
    require_space("preflight")
    conn = connect()
    try:
        with conn.cursor() as cur:
            ensure_meta(cur)
            cur.execute(
                "SELECT status FROM pubchem.rdkit_mol_version_meta WHERE singleton"
            )
            if cur.fetchone() != ("complete",):
                raise RuntimeError("RDKit version reconciliation is not complete")
            cur.execute("SELECT count(*) FROM rdkit.mols")
            if int(cur.fetchone()[0]) != EXPECTED_MOLS:
                raise RuntimeError("rdkit.mols source count changed")
            cur.execute(
                "SELECT count(*) FROM pubchem.rdkit_mol_chemical_map"
            )
            mapped_before = int(cur.fetchone()[0])
            unmatched = EXPECTED_MOLS - mapped_before
            if unmatched != EXPECTED_UNMATCHED:
                raise RuntimeError(
                    f"expected {EXPECTED_UNMATCHED} unmatched mols, got {unmatched}"
                )
            cur.execute(
                "SELECT status FROM pubchem.rdkit_mol_absorption_meta WHERE singleton"
            )
            prior = cur.fetchone()
            if prior and prior[0] == "complete":
                raise RuntimeError("unmatched RDKit absorption is already complete")
            if exists(cur, "pubchem.rdkit_mol_new_structures") and not rebuild_stage:
                raise RuntimeError(
                    "new-structure stage already exists; pass --rebuild-stage "
                    "only after reviewing it"
                )
            cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_new_structures")
            cur.execute(
                """
                INSERT INTO pubchem.rdkit_mol_absorption_meta
                    (singleton,status,unmatched_before,started_at,updated_at,
                     completed_at)
                VALUES (true,'building_stage',%s,now(),now(),NULL)
                ON CONFLICT (singleton) DO UPDATE SET
                    status=excluded.status,
                    unmatched_before=excluded.unmatched_before,
                    distinct_structures=NULL,
                    inserted_chemicals=NULL,
                    mapped_mols=NULL,
                    first_chemical_id=NULL,
                    last_chemical_id=NULL,
                    started_at=now(),updated_at=now(),completed_at=NULL
                """,
                (unmatched,),
            )
        conn.commit()

        print("building one-row-per-current-structure stage", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.rdkit_mol_new_structures AS
                SELECT s.current_smiles,
                       min(s.rdkit_mol_id)::integer AS representative_mol_id,
                       count(*)::integer AS member_count,
                       NULL::integer AS chemical_id
                FROM pubchem.rdkit_mol_current_smiles AS s
                LEFT JOIN pubchem.rdkit_mol_chemical_map AS x
                    ON x.rdkit_mol_id=s.rdkit_mol_id
                WHERE x.rdkit_mol_id IS NULL
                GROUP BY s.current_smiles
                """
            )
            cur.execute(
                """
                ALTER TABLE pubchem.rdkit_mol_new_structures
                ADD PRIMARY KEY (current_smiles),
                ADD UNIQUE (representative_mol_id),
                ADD CHECK (current_smiles IS NOT NULL),
                ADD CHECK (member_count > 0)
                """
            )
            cur.execute("ANALYZE pubchem.rdkit_mol_new_structures")
            cur.execute(
                """
                SELECT count(*),sum(member_count),max(member_count),
                       count(*) FILTER (WHERE member_count > 1)
                FROM pubchem.rdkit_mol_new_structures
                """
            )
            structures, members, max_members, duplicate_groups = (
                int(value) for value in cur.fetchone()
            )
            if members != EXPECTED_UNMATCHED:
                raise RuntimeError(f"stage member count mismatch: {members}")
            if structures != EXPECTED_UNMATCHED or max_members != 1 or duplicate_groups:
                raise RuntimeError(
                    "unexpected current-SMILES collapse: "
                    f"structures={structures}, max_members={max_members}, "
                    f"duplicate_groups={duplicate_groups}"
                )
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.rdkit_mol_new_structures AS s
                JOIN rdkit.mols AS m ON m.id=s.representative_mol_id
                WHERE m.mol IS NULL OR m.morgan_bfp IS NULL OR m.morgan_sfp IS NULL
                """
            )
            missing_derived = int(cur.fetchone()[0])
            if missing_derived:
                raise RuntimeError(
                    f"{missing_derived} source mols lack Mol or fingerprints"
                )
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_absorption_meta
                SET status='stage_verified',distinct_structures=%s,updated_at=now()
                WHERE singleton
                """,
                (structures,),
            )
        conn.commit()
        require_space("after stage")

        print("inserting autonomous chemicals and completing migration map", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH inserted AS MATERIALIZED (
                    INSERT INTO pubchem.chemicals
                        (smiles,mol,morgan_bfp,morgan_sfp,created_at,updated_at)
                    SELECT s.current_smiles,m.mol,m.morgan_bfp,m.morgan_sfp,
                           now(),now()
                    FROM pubchem.rdkit_mol_new_structures AS s
                    JOIN rdkit.mols AS m ON m.id=s.representative_mol_id
                    ORDER BY s.representative_mol_id
                    RETURNING id,smiles
                )
                UPDATE pubchem.rdkit_mol_new_structures AS s
                SET chemical_id=i.id
                FROM inserted AS i
                WHERE i.smiles=s.current_smiles
                """
            )
            inserted = cur.rowcount
            if inserted != EXPECTED_UNMATCHED:
                raise RuntimeError(
                    f"inserted chemical mapping mismatch: expected "
                    f"{EXPECTED_UNMATCHED}, got {inserted}"
                )
            cur.execute(
                """
                INSERT INTO pubchem.rdkit_mol_chemical_map
                    (rdkit_mol_id,chemical_id,match_method,candidate_count,
                     has_dsstox,evidence_score)
                SELECT s.rdkit_mol_id,n.chemical_id,'new_from_rdkit_mol',
                       1,false,0
                FROM pubchem.rdkit_mol_current_smiles AS s
                JOIN pubchem.rdkit_mol_new_structures AS n
                    ON n.current_smiles=s.current_smiles
                LEFT JOIN pubchem.rdkit_mol_chemical_map AS x
                    ON x.rdkit_mol_id=s.rdkit_mol_id
                WHERE x.rdkit_mol_id IS NULL
                """
            )
            mapped_new = cur.rowcount
            if mapped_new != EXPECTED_UNMATCHED:
                raise RuntimeError(
                    f"new mapping mismatch: expected {EXPECTED_UNMATCHED}, "
                    f"got {mapped_new}"
                )
            cur.execute(
                """
                SELECT count(*),min(n.chemical_id),max(n.chemical_id),
                       count(*) FILTER (
                           WHERE c.pubchem_cid IS NOT NULL
                              OR c.pubchem_smiles IS NOT NULL
                              OR c.smiles IS DISTINCT FROM n.current_smiles
                              OR c.mol IS NULL
                              OR c.morgan_bfp IS NULL
                              OR c.morgan_sfp IS NULL
                       )
                FROM pubchem.rdkit_mol_new_structures AS n
                JOIN pubchem.chemicals AS c ON c.id=n.chemical_id
                """
            )
            verified, first_id, last_id, broken = cur.fetchone()
            verified = int(verified)
            broken = int(broken)
            if verified != EXPECTED_UNMATCHED or broken:
                raise RuntimeError(
                    f"new chemicals failed verification: rows={verified}, broken={broken}"
                )
            cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_chemical_map")
            total_mapped = int(cur.fetchone()[0])
            if total_mapped != EXPECTED_MOLS:
                raise RuntimeError(
                    f"map is incomplete: expected {EXPECTED_MOLS}, got {total_mapped}"
                )
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_absorption_meta
                SET status='complete',inserted_chemicals=%s,mapped_mols=%s,
                    first_chemical_id=%s,last_chemical_id=%s,
                    updated_at=now(),completed_at=now()
                WHERE singleton
                """,
                (verified, mapped_new, first_id, last_id),
            )
        conn.commit()
        verify()
    except Exception:
        conn.rollback()
        try:
            with conn.cursor() as cur:
                ensure_meta(cur)
                cur.execute(
                    """
                    INSERT INTO pubchem.rdkit_mol_absorption_meta(singleton,status)
                    VALUES (true,'failed')
                    ON CONFLICT (singleton) DO UPDATE
                    SET status='failed',updated_at=now()
                    """
                )
            conn.commit()
        except Exception:
            conn.rollback()
        raise
    finally:
        conn.close()


def verify() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status,unmatched_before,distinct_structures,
                       inserted_chemicals,mapped_mols,
                       first_chemical_id,last_chemical_id
                FROM pubchem.rdkit_mol_absorption_meta WHERE singleton
                """
            )
            row = cur.fetchone()
            if row is None or row[0] != "complete":
                raise RuntimeError(f"absorption is not complete: {row}")
            cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_chemical_map")
            map_rows = int(cur.fetchone()[0])
            if map_rows != EXPECTED_MOLS:
                raise RuntimeError(f"migration map has {map_rows} rows")
            result = {
                "status": row[0],
                "unmatched_before": row[1],
                "distinct_structures": row[2],
                "inserted_chemicals": row[3],
                "mapped_mols": row[4],
                "first_chemical_id": row[5],
                "last_chemical_id": row[6],
                "total_mapped_mols": map_rows,
                "free_gib": round(shutil.disk_usage("/").free / 1024**3, 2),
            }
        conn.rollback()
        print(json.dumps(result, indent=2), flush=True)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--rebuild-stage", action="store_true")
    args = parser.parse_args()
    if args.action == "build":
        build(args.rebuild_stage)
    else:
        verify()


if __name__ == "__main__":
    main()
