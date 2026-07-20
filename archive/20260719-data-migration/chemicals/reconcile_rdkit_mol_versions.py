#!/usr/bin/env python3
"""Reconcile legacy rdkit.mols SMILES with the currently installed RDKit.

The script extends the audited migration map only when a previously unmatched
legacy Mol resolves to an existing chemical under current RDKit serialization.
It does not insert chemicals, copy fingerprints, or modify ORD references.
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
EXPECTED_CHANGED_SMILES = 5_768


def connect():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='reconcile_rdkit_mol_versions'")
        cur.execute("SET statement_timeout=0")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET work_mem='256MB'")
        cur.execute("SET maintenance_work_mem='256MB'")
        cur.execute("SET max_parallel_workers_per_gather=2")
        cur.execute("SET enable_nestloop=off")
        cur.execute("SET enable_mergejoin=off")
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


def regclass(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
    return bool(cur.fetchone()[0])


def ensure_meta(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pubchem.rdkit_mol_version_meta (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            status text NOT NULL,
            source_mols bigint,
            changed_smiles bigint,
            changed_unmatched_before bigint,
            candidate_rows bigint,
            recovered_mols bigint,
            unmatched_after bigint,
            started_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz
        )
        """
    )


def build(rebuild: bool) -> None:
    require_space("preflight")
    conn = connect()
    try:
        with conn.cursor() as cur:
            if not regclass(cur, "pubchem.rdkit_mol_chemical_map"):
                raise RuntimeError("exact migration map is missing")
            cur.execute(
                "SELECT status FROM pubchem.rdkit_mol_migration_meta WHERE singleton"
            )
            state = cur.fetchone()
            if state != ("exact_map_complete",):
                raise RuntimeError(f"exact migration map is not complete: {state}")
            ensure_meta(cur)
            if regclass(cur, "pubchem.rdkit_mol_current_smiles") and not rebuild:
                raise RuntimeError(
                    "version reconciliation tables already exist; run verify, "
                    "or pass --rebuild intentionally"
                )
            cur.execute("SELECT count(*) FROM rdkit.mols")
            source_mols = int(cur.fetchone()[0])
            if source_mols != EXPECTED_MOLS:
                raise RuntimeError(
                    f"rdkit.mols changed: expected {EXPECTED_MOLS}, got {source_mols}"
                )
            cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_current_candidates")
            cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_changed_unmatched")
            cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_current_smiles")
            cur.execute(
                """
                INSERT INTO pubchem.rdkit_mol_version_meta
                    (singleton,status,source_mols,started_at,updated_at,completed_at)
                VALUES (true,'building_current_smiles',%s,now(),now(),NULL)
                ON CONFLICT (singleton) DO UPDATE SET
                    status=excluded.status,
                    source_mols=excluded.source_mols,
                    changed_smiles=NULL,
                    changed_unmatched_before=NULL,
                    candidate_rows=NULL,
                    recovered_mols=NULL,
                    unmatched_after=NULL,
                    started_at=now(),updated_at=now(),completed_at=NULL
                """,
                (source_mols,),
            )
        conn.commit()

        print("materializing current RDKit SMILES", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.rdkit_mol_current_smiles AS
                SELECT id AS rdkit_mol_id,
                       smiles AS legacy_smiles,
                       mol_to_smiles(mol)::text AS current_smiles
                FROM rdkit.mols
                """
            )
            cur.execute(
                """
                ALTER TABLE pubchem.rdkit_mol_current_smiles
                ADD PRIMARY KEY (rdkit_mol_id)
                """
            )
            cur.execute("ANALYZE pubchem.rdkit_mol_current_smiles")
            cur.execute(
                """
                SELECT count(*),
                       count(*) FILTER (
                           WHERE legacy_smiles IS DISTINCT FROM current_smiles
                       ),
                       count(*) FILTER (WHERE current_smiles IS NULL)
                FROM pubchem.rdkit_mol_current_smiles
                """
            )
            total, changed, null_current = (int(value) for value in cur.fetchone())
            if total != EXPECTED_MOLS or changed != EXPECTED_CHANGED_SMILES:
                raise RuntimeError(
                    f"unexpected current serialization counts: "
                    f"total={total}, changed={changed}"
                )
            if null_current:
                raise RuntimeError(f"current RDKit failed to serialize {null_current} mols")

            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.rdkit_mol_changed_unmatched AS
                SELECT s.rdkit_mol_id,s.legacy_smiles,s.current_smiles
                FROM pubchem.rdkit_mol_current_smiles AS s
                LEFT JOIN pubchem.rdkit_mol_chemical_map AS x
                    ON x.rdkit_mol_id=s.rdkit_mol_id
                WHERE x.rdkit_mol_id IS NULL
                  AND s.legacy_smiles IS DISTINCT FROM s.current_smiles
                """
            )
            cur.execute(
                """
                ALTER TABLE pubchem.rdkit_mol_changed_unmatched
                ADD PRIMARY KEY (rdkit_mol_id)
                """
            )
            cur.execute("ANALYZE pubchem.rdkit_mol_changed_unmatched")
            cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_changed_unmatched")
            changed_unmatched = int(cur.fetchone()[0])
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_version_meta
                SET status='matching_current_smiles',changed_smiles=%s,
                    changed_unmatched_before=%s,updated_at=now()
                WHERE singleton
                """,
                (changed, changed_unmatched),
            )
        conn.commit()
        require_space("after current SMILES")

        print("matching changed current SMILES to existing chemicals", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                EXPLAIN
                SELECT s.rdkit_mol_id,c.id
                FROM pubchem.rdkit_mol_changed_unmatched AS s
                JOIN pubchem.chemicals AS c ON c.smiles=s.current_smiles
                WHERE c.smiles IS NOT NULL
                """
            )
            plan_text = "\n".join(row[0] for row in cur.fetchall())
            if (
                "Hash Join" not in plan_text
                or "Seq Scan on chemicals" not in plan_text
                or "Seq Scan on rdkit_mol_changed_unmatched" not in plan_text
            ):
                raise RuntimeError(f"unsafe current-SMILES join plan:\n{plan_text}")
            print(plan_text, flush=True)
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.rdkit_mol_current_candidates AS
                SELECT
                    s.rdkit_mol_id,
                    c.id AS chemical_id,
                    (c.dtxsid IS NOT NULL) AS has_dsstox,
                    (
                        (c.dtxsid IS NOT NULL)::integer * 64
                      + (c.inchikey IS NOT NULL)::integer * 32
                      + (c.preferred_name IS NOT NULL)::integer * 16
                      + (c.iupac_name IS NOT NULL)::integer * 8
                      + (coalesce(cardinality(c.cas_numbers), 0) > 0)::integer
                      + (coalesce(cardinality(c.nikkaji_numbers), 0) > 0)::integer
                      + (coalesce(cardinality(c.chembl_ids), 0) > 0)::integer
                      + (coalesce(cardinality(c.ec_numbers), 0) > 0)::integer
                      + (coalesce(cardinality(c.unii_codes), 0) > 0)::integer
                      + (coalesce(cardinality(c.chebi_ids), 0) > 0)::integer
                    )::smallint AS evidence_score
                FROM pubchem.rdkit_mol_changed_unmatched AS s
                JOIN pubchem.chemicals AS c ON c.smiles=s.current_smiles
                WHERE c.smiles IS NOT NULL
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX rdkit_mol_current_candidates_choice_idx
                ON pubchem.rdkit_mol_current_candidates
                    (rdkit_mol_id,has_dsstox DESC,evidence_score DESC,chemical_id)
                """
            )
            cur.execute("ANALYZE pubchem.rdkit_mol_current_candidates")
            cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_current_candidates")
            candidate_rows = int(cur.fetchone()[0])
            cur.execute(
                """
                WITH chosen AS MATERIALIZED (
                    SELECT DISTINCT ON (rdkit_mol_id)
                        rdkit_mol_id,chemical_id,has_dsstox,evidence_score
                    FROM pubchem.rdkit_mol_current_candidates
                    ORDER BY rdkit_mol_id,has_dsstox DESC,
                             evidence_score DESC,chemical_id
                ), counts AS MATERIALIZED (
                    SELECT rdkit_mol_id,count(*)::integer AS candidate_count
                    FROM pubchem.rdkit_mol_current_candidates
                    GROUP BY rdkit_mol_id
                )
                INSERT INTO pubchem.rdkit_mol_chemical_map
                    (rdkit_mol_id,chemical_id,match_method,candidate_count,
                     has_dsstox,evidence_score)
                SELECT chosen.rdkit_mol_id,chosen.chemical_id,
                       'current_rdkit_smiles',counts.candidate_count,
                       chosen.has_dsstox,chosen.evidence_score
                FROM chosen JOIN counts USING (rdkit_mol_id)
                ON CONFLICT (rdkit_mol_id) DO NOTHING
                """
            )
            recovered = cur.rowcount
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.rdkit_mol_chemical_map
                WHERE match_method='current_rdkit_smiles'
                """
            )
            recovered_total = int(cur.fetchone()[0])
            if recovered != recovered_total:
                raise RuntimeError(
                    f"unexpected prior recovered mappings: inserted={recovered}, "
                    f"total={recovered_total}"
                )
            unmatched_after = EXPECTED_MOLS - 1_325_509 - recovered_total
            cur.execute("SET enable_nestloop=on")
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.rdkit_mol_chemical_map AS x
                JOIN pubchem.rdkit_mol_current_smiles AS s
                    ON s.rdkit_mol_id=x.rdkit_mol_id
                JOIN pubchem.chemicals AS c ON c.id=x.chemical_id
                WHERE x.match_method='current_rdkit_smiles'
                  AND s.current_smiles IS DISTINCT FROM c.smiles
                """
            )
            broken = int(cur.fetchone()[0])
            if broken:
                raise RuntimeError(f"{broken} recovered mappings failed verification")
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_version_meta
                SET status='complete',candidate_rows=%s,recovered_mols=%s,
                    unmatched_after=%s,updated_at=now(),completed_at=now()
                WHERE singleton
                """,
                (candidate_rows, recovered_total, unmatched_after),
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
                    INSERT INTO pubchem.rdkit_mol_version_meta(singleton,status)
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
            ensure_meta(cur)
            cur.execute(
                """
                SELECT status,source_mols,changed_smiles,changed_unmatched_before,
                       candidate_rows,recovered_mols,unmatched_after
                FROM pubchem.rdkit_mol_version_meta WHERE singleton
                """
            )
            row = cur.fetchone()
            if row is None or row[0] != "complete":
                raise RuntimeError(f"version reconciliation is not complete: {row}")
            result = {
                "status": row[0],
                "source_mols": row[1],
                "changed_smiles": row[2],
                "changed_unmatched_before": row[3],
                "candidate_rows": row[4],
                "recovered_mols": row[5],
                "unmatched_after": row[6],
                "free_gib": round(shutil.disk_usage("/").free / 1024**3, 2),
            }
        conn.rollback()
        print(json.dumps(result, indent=2), flush=True)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.action == "build":
        build(args.rebuild)
    else:
        verify()


if __name__ == "__main__":
    main()
