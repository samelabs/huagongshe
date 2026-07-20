#!/usr/bin/env python3
"""Make chemicals identity source-independent without rewriting 124M rows."""

from __future__ import annotations

import json
import os

import psycopg2


DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)


def connect():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='stabilize_chemicals_schema'")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET statement_timeout=0")
    conn.commit()
    return conn


def column_state(cur):
    cur.execute(
        """
        SELECT column_name,data_type,udt_schema,udt_name,is_nullable,
               generation_expression,column_default
        FROM information_schema.columns
        WHERE table_schema='pubchem' AND table_name='chemicals'
        ORDER BY ordinal_position
        """
    )
    return {row[0]: row[1:] for row in cur.fetchall()}


def main() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            columns = column_state(cur)
            if "pubsmiles" not in columns and "pubchem_smiles" not in columns:
                raise RuntimeError("neither pubsmiles nor pubchem_smiles exists")
            if "id" not in columns or "pubchem_cid" not in columns:
                raise RuntimeError("required id/pubchem_cid columns are missing")
            already_stable = (
                columns["id"][4] in (None, "")
                and columns["pubchem_cid"][4] in (None, "")
                and "pubchem_smiles" in columns
            )
            cur.execute("SELECT max(pubchem_cid) FROM pubchem.chemicals")
            max_cid = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid='pubchem.chemicals'::regclass AND contype='p'
                """
            )
            pkey_before = cur.fetchone()[0]

        if not already_stable:
            expected_generation = columns["id"][4]
            if expected_generation != "pubchem_cid":
                raise RuntimeError(
                    f"unexpected id generation expression: {expected_generation!r}"
                )
            if pkey_before != "PRIMARY KEY (pubchem_cid)":
                raise RuntimeError(f"unexpected primary key: {pkey_before}")
            with conn.cursor() as cur:
                cur.execute("LOCK TABLE pubchem.chemicals IN ACCESS EXCLUSIVE MODE")
                cur.execute(
                    "ALTER TABLE pubchem.chemicals RENAME COLUMN id TO _pubchem_cid_copy"
                )
                cur.execute(
                    "ALTER TABLE pubchem.chemicals RENAME COLUMN pubchem_cid TO id"
                )
                cur.execute(
                    "ALTER TABLE pubchem.chemicals RENAME COLUMN _pubchem_cid_copy TO pubchem_cid"
                )
                cur.execute(
                    "ALTER TABLE pubchem.chemicals ALTER COLUMN pubchem_cid DROP EXPRESSION"
                )
                cur.execute(
                    "ALTER TABLE pubchem.chemicals RENAME COLUMN pubsmiles TO pubchem_smiles"
                )
                cur.execute(
                    "ALTER TABLE pubchem.chemicals ALTER COLUMN pubchem_smiles DROP NOT NULL"
                )
                cur.execute(
                    "CREATE SEQUENCE pubchem.chemicals_id_seq AS integer"
                )
                cur.execute(
                    "SELECT setval('pubchem.chemicals_id_seq', %s, true)",
                    (max_cid,),
                )
                cur.execute(
                    "ALTER SEQUENCE pubchem.chemicals_id_seq OWNED BY pubchem.chemicals.id"
                )
                cur.execute(
                    "ALTER TABLE pubchem.chemicals ALTER COLUMN id "
                    "SET DEFAULT nextval('pubchem.chemicals_id_seq')"
                )
                cur.execute(
                    """
                    ALTER TABLE pubchem.chemicals
                        ADD COLUMN mol public.mol,
                        ADD COLUMN morgan_bfp public.bfp,
                        ADD COLUMN morgan_sfp public.sfp
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE pubchem.chemicals
                    ADD CONSTRAINT chemicals_pubchem_identity_guard
                    CHECK (pubchem_cid IS NULL OR pubchem_cid=id) NOT VALID
                    """
                )
                cur.execute(
                    """
                    COMMENT ON COLUMN pubchem.chemicals.id IS
                        'Autonomous chemical identity; independent of source namespaces';
                    COMMENT ON COLUMN pubchem.chemicals.pubchem_cid IS
                        'Nullable PubChem source identifier; no longer the primary key';
                    COMMENT ON COLUMN pubchem.chemicals.pubchem_smiles IS
                        'Raw PubChem source SMILES; nullable for non-PubChem chemicals';
                    COMMENT ON COLUMN pubchem.chemicals.smiles IS
                        'Canonical RDKit structure expression owned by chemicals';
                    COMMENT ON COLUMN pubchem.chemicals.mol IS
                        'Derived RDKit Cartridge Mol; rebuildable from chemicals.smiles';
                    COMMENT ON COLUMN pubchem.chemicals.morgan_bfp IS
                        'Derived Morgan bit fingerprint for similarity search';
                    COMMENT ON COLUMN pubchem.chemicals.morgan_sfp IS
                        'Derived Morgan sparse fingerprint for similarity search'
                    """
                )
            conn.commit()

        with conn.cursor() as cur:
            columns = column_state(cur)
            cur.execute(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid='pubchem.chemicals'::regclass AND contype='p'
                """
            )
            pkey_after = cur.fetchone()[0]
            cur.execute(
                """
                SELECT last_value,is_called
                FROM pubchem.chemicals_id_seq
                """
            )
            sequence_state = cur.fetchone()
            if columns["id"][4] not in (None, ""):
                raise RuntimeError("id is still generated")
            if columns["pubchem_cid"][4] not in (None, ""):
                raise RuntimeError("pubchem_cid is still generated")
            if columns["pubchem_cid"][3] != "YES":
                raise RuntimeError("pubchem_cid is not nullable")
            if columns["pubchem_smiles"][3] != "YES":
                raise RuntimeError("pubchem_smiles is not nullable")
            if pkey_after != "PRIMARY KEY (id)":
                raise RuntimeError(f"primary key was not transferred to id: {pkey_after}")
            for required in ("mol", "morgan_bfp", "morgan_sfp"):
                if required not in columns:
                    raise RuntimeError(f"missing derived search column: {required}")

            cur.execute("SAVEPOINT insertion_test")
            cur.execute(
                """
                INSERT INTO pubchem.chemicals(smiles,created_at,updated_at)
                VALUES ('[He]',now(),now())
                RETURNING id,pubchem_cid,pubchem_smiles
                """
            )
            test_row = cur.fetchone()
            cur.execute("ROLLBACK TO SAVEPOINT insertion_test")
            if test_row[0] <= max_cid or test_row[1:] != (None, None):
                raise RuntimeError(f"autonomous insert test failed: {test_row}")
        conn.rollback()
        print(
            json.dumps(
                {
                    "status": "stable",
                    "max_existing_id": max_cid,
                    "primary_key": pkey_after,
                    "sequence_last_value": sequence_state[0],
                    "sequence_is_called": sequence_state[1],
                    "autonomous_insert_test": {
                        "id": test_row[0],
                        "pubchem_cid": test_row[1],
                        "pubchem_smiles": test_row[2],
                        "rolled_back": True,
                    },
                    "columns": list(columns),
                },
                indent=2,
            )
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
