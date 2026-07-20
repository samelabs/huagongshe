#!/usr/bin/env python3
"""Build sparse RDKit search indexes on the chemicals-owned payload."""

from __future__ import annotations

import json
import os
import shutil

import psycopg2


DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
MIN_FREE_BYTES = 5 * 1024**3
INDEXES = (
    (
        "chemicals_rdkit_smiles_idx",
        "CREATE INDEX chemicals_rdkit_smiles_idx "
        "ON pubchem.chemicals(smiles) WHERE mol IS NOT NULL",
    ),
    (
        "chemicals_mol_gist_idx",
        "CREATE INDEX chemicals_mol_gist_idx "
        "ON pubchem.chemicals USING gist(mol) WHERE mol IS NOT NULL",
    ),
    (
        "chemicals_morgan_bfp_gist_idx",
        "CREATE INDEX chemicals_morgan_bfp_gist_idx "
        "ON pubchem.chemicals USING gist(morgan_bfp) "
        "WHERE mol IS NOT NULL",
    ),
    (
        "chemicals_morgan_sfp_gist_idx",
        "CREATE INDEX chemicals_morgan_sfp_gist_idx "
        "ON pubchem.chemicals USING gist(morgan_sfp) "
        "WHERE mol IS NOT NULL",
    ),
)


def free_gib() -> float:
    return shutil.disk_usage("/").free / 1024**3


def main() -> None:
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET application_name='build_chemicals_rdkit_indexes'")
            cur.execute("SET statement_timeout=0")
            cur.execute("SET lock_timeout='30s'")
            cur.execute("SET maintenance_work_mem='256MB'")
            cur.execute(
                "SELECT relkind FROM pg_class WHERE oid=to_regclass('rdkit.mols')"
            )
            if cur.fetchone() != ("v",):
                raise RuntimeError("rdkit.mols compatibility view is not installed")
            cur.execute(
                "SELECT status,copied_rows FROM pubchem.rdkit_mol_payload_meta "
                "WHERE singleton"
            )
            if cur.fetchone() != ("complete", 1_325_511):
                raise RuntimeError("payload copy is not complete")

            for name, ddl in INDEXES:
                cur.execute(
                    """
                    SELECT i.indisvalid,i.indisready
                    FROM pg_index AS i
                    WHERE i.indexrelid=to_regclass(%s)
                    """,
                    (f"pubchem.{name}",),
                )
                state = cur.fetchone()
                if state == (True, True):
                    print(f"{name}: already valid", flush=True)
                    continue
                if state is not None:
                    raise RuntimeError(f"{name}: existing invalid index {state}")
                if shutil.disk_usage("/").free < MIN_FREE_BYTES:
                    raise RuntimeError(
                        f"{name}: hard disk floor reached ({free_gib():.2f} GiB)"
                    )
                print(f"{name}: building; free={free_gib():.2f}GiB", flush=True)
                cur.execute(ddl)
                cur.execute(
                    "SELECT indisvalid,indisready FROM pg_index "
                    "WHERE indexrelid=to_regclass(%s)",
                    (f"pubchem.{name}",),
                )
                if cur.fetchone() != (True, True):
                    raise RuntimeError(f"{name}: index did not become valid")
                print(f"{name}: complete; free={free_gib():.2f}GiB", flush=True)

            cur.execute(
                "ANALYZE pubchem.chemicals (smiles,mol,morgan_bfp,morgan_sfp)"
            )
            cur.execute(
                """
                SELECT c.relname,pg_relation_size(c.oid),i.indisvalid,i.indisready
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid=c.relnamespace
                JOIN pg_index AS i ON i.indexrelid=c.oid
                WHERE n.nspname='pubchem' AND c.relname=ANY(%s)
                ORDER BY c.relname
                """,
                ([item[0] for item in INDEXES],),
            )
            rows = cur.fetchall()
        print(
            json.dumps(
                {
                    "status": "complete",
                    "indexes": [
                        {
                            "name": row[0],
                            "bytes": row[1],
                            "valid": row[2],
                            "ready": row[3],
                        }
                        for row in rows
                    ],
                    "free_gib": round(free_gib(), 2),
                },
                indent=2,
            ),
            flush=True,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
