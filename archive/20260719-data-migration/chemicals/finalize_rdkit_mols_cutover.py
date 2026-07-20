#!/usr/bin/env python3
"""Verify chemicals payload and retire physical rdkit.mols in guarded phases.

The compact ORD bridge preserves legacy integer references without treating
them as chemical identity.  A read-only rdkit.mols compatibility view keeps
legacy SELECT callers working while application code moves to chemical_id.
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
EXPECTED_MOLS = 1_435_401


def connect(hash_scan: bool = False):
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='finalize_rdkit_mols_cutover'")
        cur.execute("SET statement_timeout=0")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET work_mem='512MB'")
        cur.execute("SET maintenance_work_mem='256MB'")
        if hash_scan:
            cur.execute("SET enable_nestloop=off")
            cur.execute("SET enable_mergejoin=off")
        cur.execute("SET synchronous_commit=off")
    conn.commit()
    return conn


def kind(cur, name: str):
    cur.execute(
        "SELECT relkind FROM pg_class WHERE oid=to_regclass(%s)",
        (name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def require_completed_sources(cur) -> None:
    cur.execute(
        "SELECT status,copied_rows FROM pubchem.rdkit_mol_payload_meta WHERE singleton"
    )
    payload = cur.fetchone()
    cur.execute(
        "SELECT status,inserted_chemicals FROM pubchem.rdkit_mol_absorption_meta "
        "WHERE singleton"
    )
    absorbed = cur.fetchone()
    if payload != ("complete", 1_325_511):
        raise RuntimeError(f"payload phase incomplete: {payload}")
    if absorbed != ("complete", 109_890):
        raise RuntimeError(f"absorption phase incomplete: {absorbed}")


def verify_payload() -> None:
    conn = connect(hash_scan=True)
    try:
        with conn.cursor() as cur:
            require_completed_sources(cur)
            if kind(cur, "rdkit.mols") != "r":
                raise RuntimeError("physical rdkit.mols table is not present")
            cur.execute(
                """
                EXPLAIN
                SELECT count(*)
                FROM pubchem.rdkit_mol_chemical_map AS x
                JOIN pubchem.chemicals AS c ON c.id=x.chemical_id
                WHERE c.mol IS NULL OR c.morgan_bfp IS NULL OR c.morgan_sfp IS NULL
                """
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
            if "Hash Join" not in plan or "Seq Scan on chemicals" not in plan:
                raise RuntimeError(f"unsafe payload verification plan:\n{plan}")
            print(plan, flush=True)
            cur.execute(
                """
                SELECT count(*),
                       count(*) FILTER (
                           WHERE c.mol IS NULL
                              OR c.morgan_bfp IS NULL
                              OR c.morgan_sfp IS NULL
                       ),
                       count(DISTINCT x.rdkit_mol_id),
                       count(DISTINCT x.chemical_id)
                FROM pubchem.rdkit_mol_chemical_map AS x
                JOIN pubchem.chemicals AS c ON c.id=x.chemical_id
                """
            )
            total, missing, mol_ids, chemical_ids = (
                int(value) for value in cur.fetchone()
            )
            if (total, missing, mol_ids, chemical_ids) != (
                EXPECTED_MOLS,
                0,
                EXPECTED_MOLS,
                EXPECTED_MOLS,
            ):
                raise RuntimeError(
                    "payload verification failed: "
                    f"{(total, missing, mol_ids, chemical_ids)}"
                )
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.rdkit_mol_new_structures AS n
                JOIN pubchem.chemicals AS c ON c.id=n.chemical_id
                WHERE c.pubchem_cid IS NOT NULL OR c.pubchem_smiles IS NOT NULL
                """
            )
            source_leaks = int(cur.fetchone()[0])
            if source_leaks:
                raise RuntimeError(
                    f"{source_leaks} ORD-only chemicals incorrectly carry PubChem identity"
                )
        conn.rollback()
        print(
            json.dumps(
                {
                    "status": "payload_verified",
                    "mapped_mols": total,
                    "mapped_chemicals": chemical_ids,
                    "missing_payload": missing,
                    "ord_only_pubchem_identity_leaks": source_leaks,
                    "free_gib": round(shutil.disk_usage("/").free / 1024**3, 2),
                },
                indent=2,
            ),
            flush=True,
        )
    finally:
        conn.close()


def build_bridge(rebuild: bool) -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            require_completed_sources(cur)
            bridge_kind = kind(cur, "ord.legacy_rdkit_mol_map")
            if bridge_kind and not rebuild:
                raise RuntimeError("ORD legacy bridge already exists")
            cur.execute("DROP TABLE IF EXISTS ord.legacy_rdkit_mol_map")
            cur.execute(
                """
                CREATE TABLE ord.legacy_rdkit_mol_map (
                    legacy_mol_id integer PRIMARY KEY,
                    chemical_id integer NOT NULL UNIQUE
                )
                """
            )
            cur.execute(
                """
                INSERT INTO ord.legacy_rdkit_mol_map(legacy_mol_id,chemical_id)
                SELECT rdkit_mol_id,chemical_id
                FROM pubchem.rdkit_mol_chemical_map
                ORDER BY rdkit_mol_id
                """
            )
            inserted = cur.rowcount
            if inserted != EXPECTED_MOLS:
                raise RuntimeError(f"bridge inserted {inserted} rows")
            cur.execute(
                """
                ALTER TABLE ord.legacy_rdkit_mol_map
                ADD CONSTRAINT legacy_rdkit_mol_map_chemical_id_fkey
                FOREIGN KEY (chemical_id) REFERENCES pubchem.chemicals(id)
                ON DELETE RESTRICT NOT VALID
                """
            )
            cur.execute(
                """
                COMMENT ON TABLE ord.legacy_rdkit_mol_map IS
                    'Temporary compatibility bridge from historical rdkit.mols.id '
                    'to autonomous chemicals.id; not a chemical identity table';
                COMMENT ON COLUMN ord.legacy_rdkit_mol_map.legacy_mol_id IS
                    'Historical locator retained only while ORD references migrate';
                COMMENT ON COLUMN ord.legacy_rdkit_mol_map.chemical_id IS
                    'Canonical project-owned chemical identity'
                """
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE ord.legacy_rdkit_mol_map
                VALIDATE CONSTRAINT legacy_rdkit_mol_map_chemical_id_fkey
                """
            )
            cur.execute("ANALYZE ord.legacy_rdkit_mol_map")
        conn.commit()
        print(
            json.dumps(
                {
                    "status": "bridge_complete",
                    "rows": inserted,
                    "free_gib": round(shutil.disk_usage("/").free / 1024**3, 2),
                },
                indent=2,
            ),
            flush=True,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def switch_ord_foreign_keys() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            if kind(cur, "ord.legacy_rdkit_mol_map") != "r":
                raise RuntimeError("ORD legacy bridge is missing")
            cur.execute("SELECT count(*) FROM ord.legacy_rdkit_mol_map")
            if int(cur.fetchone()[0]) != EXPECTED_MOLS:
                raise RuntimeError("ORD legacy bridge is incomplete")
            cur.execute(
                """
                ALTER TABLE ord.compound
                    DROP CONSTRAINT compound_rdkit_mol_id_fkey,
                    ADD CONSTRAINT compound_rdkit_mol_id_fkey
                    FOREIGN KEY (rdkit_mol_id)
                    REFERENCES ord.legacy_rdkit_mol_map(legacy_mol_id)
                    ON DELETE RESTRICT NOT VALID;
                ALTER TABLE ord.product_compound
                    DROP CONSTRAINT product_compound_rdkit_mol_id_fkey,
                    ADD CONSTRAINT product_compound_rdkit_mol_id_fkey
                    FOREIGN KEY (rdkit_mol_id)
                    REFERENCES ord.legacy_rdkit_mol_map(legacy_mol_id)
                    ON DELETE RESTRICT NOT VALID
                """
            )
        conn.commit()
        print("ORD foreign keys switched; validating compound", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE ord.compound
                VALIDATE CONSTRAINT compound_rdkit_mol_id_fkey
                """
            )
        conn.commit()
        print("validating product_compound", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE ord.product_compound
                VALIDATE CONSTRAINT product_compound_rdkit_mol_id_fkey
                """
            )
            cur.execute(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname IN (
                    'compound_rdkit_mol_id_fkey',
                    'product_compound_rdkit_mol_id_fkey'
                )
                  AND confrelid='ord.legacy_rdkit_mol_map'::regclass
                  AND convalidated
                """
            )
            validated = int(cur.fetchone()[0])
            if validated != 2:
                raise RuntimeError(f"only {validated} ORD foreign keys validated")
        conn.commit()
        print(json.dumps({"status": "ord_foreign_keys_switched"}, indent=2))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def install_compatibility_view() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            require_completed_sources(cur)
            if kind(cur, "ord.legacy_rdkit_mol_map") != "r":
                raise RuntimeError("ORD legacy bridge is missing")
            cur.execute(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname IN (
                    'compound_rdkit_mol_id_fkey',
                    'product_compound_rdkit_mol_id_fkey'
                )
                  AND confrelid='ord.legacy_rdkit_mol_map'::regclass
                  AND convalidated
                """
            )
            if int(cur.fetchone()[0]) != 2:
                raise RuntimeError("ORD foreign keys are not safely switched")
            if kind(cur, "rdkit.mols") != "r":
                raise RuntimeError("expected physical rdkit.mols before cutover")
            if kind(cur, "rdkit.mols_legacy") is not None:
                raise RuntimeError("rdkit.mols_legacy already exists")
            cur.execute("ALTER TABLE rdkit.mols RENAME TO mols_legacy")
            cur.execute(
                """
                CREATE VIEW rdkit.mols AS
                SELECT b.legacy_mol_id AS id,
                       c.smiles,
                       c.mol,
                       c.morgan_bfp,
                       c.morgan_sfp
                FROM ord.legacy_rdkit_mol_map AS b
                JOIN pubchem.chemicals AS c ON c.id=b.chemical_id
                WHERE c.mol IS NOT NULL
                """
            )
            cur.execute(
                """
                COMMENT ON VIEW rdkit.mols IS
                    'Read-only compatibility projection; chemicals owns all '
                    'structure and fingerprint data'
                """
            )
            cur.execute(
                """
                SELECT count(*)
                FROM (
                    SELECT id FROM rdkit.mols ORDER BY id LIMIT 1000
                ) AS sample
                """
            )
            if int(cur.fetchone()[0]) != 1000:
                raise RuntimeError("compatibility view sample failed")
            cur.execute(
                """
                SELECT id,smiles,mol IS NOT NULL,morgan_bfp IS NOT NULL,
                       morgan_sfp IS NOT NULL
                FROM rdkit.mols WHERE id=1
                """
            )
            sample = cur.fetchone()
        conn.commit()
        print(
            json.dumps(
                {"status": "compatibility_view_installed", "sample_id_1": sample},
                indent=2,
            ),
            flush=True,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def drop_legacy_table() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            if kind(cur, "rdkit.mols") != "v":
                raise RuntimeError("rdkit.mols compatibility view is missing")
            if kind(cur, "rdkit.mols_legacy") != "r":
                raise RuntimeError("legacy physical table is missing")
            cur.execute(
                """
                SELECT count(*) FROM pg_constraint
                WHERE confrelid='rdkit.mols_legacy'::regclass
                """
            )
            dependencies = int(cur.fetchone()[0])
            if dependencies:
                raise RuntimeError(
                    f"legacy table still has {dependencies} referencing constraints"
                )
            cur.execute("DROP TABLE rdkit.mols_legacy")
        conn.commit()
        print(
            json.dumps(
                {
                    "status": "legacy_table_dropped",
                    "compatibility_relation": "rdkit.mols view",
                    "free_gib": round(shutil.disk_usage("/").free / 1024**3, 2),
                },
                indent=2,
            ),
            flush=True,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def status() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            result = {}
            for name in (
                "rdkit.mols",
                "rdkit.mols_legacy",
                "ord.legacy_rdkit_mol_map",
            ):
                result[name] = kind(cur, name)
            cur.execute(
                """
                SELECT conname,convalidated,confrelid::regclass::text
                FROM pg_constraint
                WHERE conname IN (
                    'compound_rdkit_mol_id_fkey',
                    'product_compound_rdkit_mol_id_fkey'
                ) ORDER BY conname
                """
            )
            result["ord_foreign_keys"] = cur.fetchall()
            result["free_gib"] = round(shutil.disk_usage("/").free / 1024**3, 2)
        conn.rollback()
        print(json.dumps(result, indent=2))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "verify-payload",
            "build-bridge",
            "switch-ord-fks",
            "install-view",
            "drop-legacy",
            "status",
        ),
    )
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.action == "verify-payload":
        verify_payload()
    elif args.action == "build-bridge":
        build_bridge(args.rebuild)
    elif args.action == "switch-ord-fks":
        switch_ord_foreign_keys()
    elif args.action == "install-view":
        install_compatibility_view()
    elif args.action == "drop-legacy":
        drop_legacy_table()
    else:
        status()


if __name__ == "__main__":
    main()
