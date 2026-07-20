#!/usr/bin/env python3
"""Build an auditable, non-domain migration map from rdkit.mols to chemicals.

This phase never changes ORD foreign keys and never copies Mol/fingerprints.  It
only records exact canonical-SMILES candidates and chooses one deterministic
chemical_id per legacy rdkit.mols.id.  Candidate rows are retained so every
choice can be reviewed before the next migration phase.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from typing import Any

import psycopg2


DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
MIN_FREE_BYTES = 5 * 1024**3

# These guards describe the verified live snapshot.  A changed source must be
# diagnosed explicitly instead of silently producing a different migration.
EXPECTED_MOLS = 1_435_401
EXPECTED_CANDIDATES = 1_327_047
EXPECTED_MATCHED_MOLS = 1_325_509
EXPECTED_UNMATCHED_MOLS = 109_892
EXPECTED_AMBIGUOUS_MOLS = 1_381


def connect():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='map_rdkit_mols_to_chemicals'")
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


def free_bytes() -> int:
    return shutil.disk_usage("/").free


def require_space(stage: str) -> None:
    available = free_bytes()
    if available < MIN_FREE_BYTES:
        raise RuntimeError(
            f"{stage}: only {available / 1024**3:.2f} GiB free; "
            f"hard floor is {MIN_FREE_BYTES / 1024**3:.2f} GiB"
        )


def relation_exists(cur, qualified_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (qualified_name,))
    return bool(cur.fetchone()[0])


def plan() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                EXPLAIN (FORMAT JSON, VERBOSE)
                SELECT m.id AS rdkit_mol_id, c.id AS chemical_id
                FROM rdkit.mols AS m
                JOIN pubchem.chemicals AS c ON c.smiles = m.smiles
                WHERE c.smiles IS NOT NULL
                """
            )
            doc = cur.fetchone()[0][0]
        conn.rollback()
    finally:
        conn.close()

    def nodes(node: dict[str, Any]):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    plan_nodes = list(nodes(doc["Plan"]))
    has_hash_join = any("Hash Join" in n.get("Node Type", "") for n in plan_nodes)
    hashes_mols = any(
        n.get("Node Type") in ("Seq Scan", "Parallel Seq Scan")
        and n.get("Schema") == "rdkit"
        and n.get("Relation Name") == "mols"
        and any(
            parent.get("Node Type") in ("Hash", "Parallel Hash")
            for parent in plan_nodes
            if n in parent.get("Plans", [])
        )
        for n in plan_nodes
    )
    if not has_hash_join or not hashes_mols:
        raise RuntimeError("unsafe join plan: expected chemicals scan hashing rdkit.mols")
    print(json.dumps(doc, indent=2), flush=True)


def ensure_meta(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pubchem.rdkit_mol_migration_meta (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            status text NOT NULL,
            rdkit_extension_version text,
            source_mols bigint,
            candidate_rows bigint,
            matched_mols bigint,
            unmatched_mols bigint,
            ambiguous_mols bigint,
            started_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz
        )
        """
    )


def source_count(cur) -> int:
    cur.execute("SELECT count(*) FROM rdkit.mols")
    value = int(cur.fetchone()[0])
    if value != EXPECTED_MOLS:
        raise RuntimeError(f"rdkit.mols changed: expected {EXPECTED_MOLS}, got {value}")
    return value


def build(rebuild: bool) -> None:
    require_space("preflight")
    plan()
    conn = connect()
    try:
        with conn.cursor() as cur:
            ensure_meta(cur)
            if relation_exists(cur, "pubchem.rdkit_mol_chemical_map") and not rebuild:
                cur.execute(
                    "SELECT status FROM pubchem.rdkit_mol_migration_meta WHERE singleton"
                )
                state = cur.fetchone()
                raise RuntimeError(
                    "migration tables already exist"
                    + (f" with status={state[0]}" if state else "")
                    + "; run verify, or pass --rebuild intentionally"
                )
            source_mols = source_count(cur)
            cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_chemical_map")
            cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_chemical_candidates")
            cur.execute(
                """
                INSERT INTO pubchem.rdkit_mol_migration_meta
                    (singleton,status,rdkit_extension_version,source_mols,
                     started_at,updated_at,completed_at)
                SELECT true,'building_candidates',extversion,%s,now(),now(),NULL
                FROM pg_extension WHERE extname='rdkit'
                ON CONFLICT (singleton) DO UPDATE SET
                    status=excluded.status,
                    rdkit_extension_version=excluded.rdkit_extension_version,
                    source_mols=excluded.source_mols,
                    candidate_rows=NULL,
                    matched_mols=NULL,
                    unmatched_mols=NULL,
                    ambiguous_mols=NULL,
                    started_at=now(),
                    updated_at=now(),
                    completed_at=NULL
                """,
                (source_mols,),
            )
        conn.commit()

        print("building exact-SMILES candidate table", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.rdkit_mol_chemical_candidates AS
                SELECT
                    m.id AS rdkit_mol_id,
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
                FROM rdkit.mols AS m
                JOIN pubchem.chemicals AS c ON c.smiles = m.smiles
                WHERE c.smiles IS NOT NULL
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX rdkit_mol_candidates_choice_idx
                ON pubchem.rdkit_mol_chemical_candidates
                    (rdkit_mol_id,has_dsstox DESC,evidence_score DESC,chemical_id)
                """
            )
            cur.execute("ANALYZE pubchem.rdkit_mol_chemical_candidates")
            cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_chemical_candidates")
            candidates = int(cur.fetchone()[0])
            if candidates != EXPECTED_CANDIDATES:
                raise RuntimeError(
                    f"candidate count changed: expected {EXPECTED_CANDIDATES}, "
                    f"got {candidates}"
                )
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_migration_meta
                SET status='building_map',candidate_rows=%s,updated_at=now()
                WHERE singleton
                """,
                (candidates,),
            )
        conn.commit()
        require_space("after candidates")

        print("choosing deterministic chemical_id mappings", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.rdkit_mol_chemical_map AS
                WITH chosen AS MATERIALIZED (
                    SELECT DISTINCT ON (rdkit_mol_id)
                        rdkit_mol_id,chemical_id,has_dsstox,evidence_score
                    FROM pubchem.rdkit_mol_chemical_candidates
                    ORDER BY rdkit_mol_id,has_dsstox DESC,
                             evidence_score DESC,chemical_id
                ), counts AS MATERIALIZED (
                    SELECT rdkit_mol_id,count(*)::integer AS candidate_count
                    FROM pubchem.rdkit_mol_chemical_candidates
                    GROUP BY rdkit_mol_id
                )
                SELECT
                    chosen.rdkit_mol_id,
                    chosen.chemical_id,
                    'exact_smiles'::text AS match_method,
                    counts.candidate_count,
                    chosen.has_dsstox,
                    chosen.evidence_score
                FROM chosen
                JOIN counts USING (rdkit_mol_id)
                """
            )
            cur.execute(
                """
                ALTER TABLE pubchem.rdkit_mol_chemical_map
                ADD PRIMARY KEY (rdkit_mol_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX rdkit_mol_chemical_map_chemical_idx
                ON pubchem.rdkit_mol_chemical_map(chemical_id)
                """
            )
            cur.execute("ANALYZE pubchem.rdkit_mol_chemical_map")
        conn.commit()
        verify(update_meta=True)
    except Exception:
        conn.rollback()
        try:
            with conn.cursor() as cur:
                ensure_meta(cur)
                cur.execute(
                    """
                    INSERT INTO pubchem.rdkit_mol_migration_meta(singleton,status)
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


def verify(update_meta: bool = False) -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            if not relation_exists(cur, "pubchem.rdkit_mol_chemical_map"):
                raise RuntimeError("mapping table does not exist")
            source_mols = source_count(cur)
            cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_chemical_candidates")
            candidate_rows = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT count(*),count(*) FILTER (WHERE candidate_count > 1),
                       min(candidate_count),max(candidate_count),
                       count(*) FILTER (WHERE match_method <> 'exact_smiles')
                FROM pubchem.rdkit_mol_chemical_map
                WHERE match_method='exact_smiles'
                """
            )
            matched, ambiguous, min_candidates, max_candidates, wrong_method = (
                int(value) for value in cur.fetchone()
            )
            unmatched = source_mols - matched
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.rdkit_mol_chemical_map AS x
                LEFT JOIN rdkit.mols AS m ON m.id=x.rdkit_mol_id
                LEFT JOIN pubchem.chemicals AS c ON c.id=x.chemical_id
                WHERE x.match_method='exact_smiles'
                  AND (m.id IS NULL OR c.id IS NULL
                       OR m.smiles IS DISTINCT FROM c.smiles)
                """
            )
            broken = int(cur.fetchone()[0])
            observed = {
                "source_mols": source_mols,
                "candidate_rows": candidate_rows,
                "matched_mols": matched,
                "unmatched_mols": unmatched,
                "ambiguous_mols": ambiguous,
                "min_candidates": min_candidates,
                "max_candidates": max_candidates,
                "wrong_method": wrong_method,
                "broken_links_or_smiles": broken,
                "free_gib": round(free_bytes() / 1024**3, 2),
            }
            expected = {
                "candidate_rows": EXPECTED_CANDIDATES,
                "matched_mols": EXPECTED_MATCHED_MOLS,
                "unmatched_mols": EXPECTED_UNMATCHED_MOLS,
                "ambiguous_mols": EXPECTED_AMBIGUOUS_MOLS,
                "wrong_method": 0,
                "broken_links_or_smiles": 0,
            }
            failures = {
                key: (observed[key], value)
                for key, value in expected.items()
                if observed[key] != value
            }
            if failures:
                raise RuntimeError(f"mapping verification failed: {failures}")
            if update_meta:
                cur.execute(
                    """
                    UPDATE pubchem.rdkit_mol_migration_meta
                    SET status='exact_map_complete',candidate_rows=%s,
                        matched_mols=%s,unmatched_mols=%s,ambiguous_mols=%s,
                        updated_at=now(),completed_at=now()
                    WHERE singleton
                    """,
                    (candidate_rows, matched, unmatched, ambiguous),
                )
                conn.commit()
            else:
                conn.rollback()
        print(json.dumps(observed, indent=2), flush=True)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "build", "verify"))
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="intentionally replace prior migration-only candidate/map tables",
    )
    args = parser.parse_args()
    if args.action == "plan":
        plan()
    elif args.action == "build":
        build(args.rebuild)
    else:
        verify()


if __name__ == "__main__":
    main()
