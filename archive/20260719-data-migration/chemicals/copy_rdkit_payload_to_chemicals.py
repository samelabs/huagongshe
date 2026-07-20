#!/usr/bin/env python3
"""Resumably copy legacy Mol/fingerprints into mapped existing chemicals."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time

import psycopg2


DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
MIN_FREE_BYTES = 5 * 1024**3
EXPECTED_SOURCE_MOLS = 1_435_401
EXPECTED_NEW_CHEMICALS = 109_890
EXPECTED_COPY_ROWS = EXPECTED_SOURCE_MOLS - EXPECTED_NEW_CHEMICALS
DEFAULT_BATCH_ROWS = 20_000


def connect():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='copy_rdkit_payload_to_chemicals'")
        cur.execute("SET statement_timeout=0")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET work_mem='128MB'")
        cur.execute("SET maintenance_work_mem='256MB'")
        cur.execute("SET enable_hashjoin=off")
        cur.execute("SET enable_mergejoin=off")
        cur.execute("SET synchronous_commit=off")
    conn.commit()
    return conn


def free_bytes() -> int:
    return shutil.disk_usage("/").free


def ensure_meta(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pubchem.rdkit_mol_payload_meta (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            status text NOT NULL,
            target_rows bigint,
            copied_rows bigint NOT NULL DEFAULT 0,
            last_chemical_id integer NOT NULL DEFAULT 0,
            batch_rows integer,
            started_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz
        )
        """
    )


def relation_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
    return bool(cur.fetchone()[0])


def build_queue(conn, rebuild: bool, batch_rows: int) -> None:
    with conn.cursor() as cur:
        ensure_meta(cur)
        cur.execute(
            "SELECT status,copied_rows FROM pubchem.rdkit_mol_payload_meta WHERE singleton"
        )
        prior = cur.fetchone()
        queue_exists = relation_exists(cur, "pubchem.rdkit_mol_payload_queue")
        if queue_exists and not rebuild:
            if prior and prior[0] in ("copying", "paused_space", "complete"):
                return
            raise RuntimeError("payload queue exists in an unexpected state")
        if rebuild and prior and int(prior[1] or 0) > 0:
            raise RuntimeError("refusing to rebuild queue after payload copying began")
        cur.execute("DROP TABLE IF EXISTS pubchem.rdkit_mol_payload_queue")
        cur.execute(
            """
            CREATE UNLOGGED TABLE pubchem.rdkit_mol_payload_queue AS
            SELECT chemical_id,rdkit_mol_id
            FROM pubchem.rdkit_mol_chemical_map
            WHERE match_method <> 'new_from_rdkit_mol'
            """
        )
        cur.execute(
            """
            ALTER TABLE pubchem.rdkit_mol_payload_queue
            ADD PRIMARY KEY (chemical_id),
            ADD UNIQUE (rdkit_mol_id)
            """
        )
        cur.execute("ANALYZE pubchem.rdkit_mol_payload_queue")
        cur.execute("SELECT count(*) FROM pubchem.rdkit_mol_payload_queue")
        target = int(cur.fetchone()[0])
        if target != EXPECTED_COPY_ROWS:
            raise RuntimeError(
                f"payload target changed: expected {EXPECTED_COPY_ROWS}, got {target}"
            )
        cur.execute(
            """
            INSERT INTO pubchem.rdkit_mol_payload_meta
                (singleton,status,target_rows,copied_rows,last_chemical_id,
                 batch_rows,started_at,updated_at,completed_at)
            VALUES (true,'copying',%s,0,0,%s,now(),now(),NULL)
            ON CONFLICT (singleton) DO UPDATE SET
                status='copying',target_rows=excluded.target_rows,copied_rows=0,
                last_chemical_id=0,batch_rows=excluded.batch_rows,
                started_at=now(),updated_at=now(),completed_at=NULL
            """,
            (target, batch_rows),
        )
    conn.commit()


def plan_guard(cur, last_id: int, batch_rows: int) -> str:
    cur.execute(
        """
        EXPLAIN
        WITH batch AS MATERIALIZED (
            SELECT chemical_id,rdkit_mol_id
            FROM pubchem.rdkit_mol_payload_queue
            WHERE chemical_id > %s
            ORDER BY chemical_id
            LIMIT %s
        )
        UPDATE pubchem.chemicals AS c
        SET mol=m.mol,morgan_bfp=m.morgan_bfp,morgan_sfp=m.morgan_sfp
        FROM batch AS b
        JOIN rdkit.mols AS m ON m.id=b.rdkit_mol_id
        WHERE c.id=b.chemical_id
          AND c.mol IS NULL
          AND c.morgan_bfp IS NULL
          AND c.morgan_sfp IS NULL
        """,
        (last_id, batch_rows),
    )
    text = "\n".join(row[0] for row in cur.fetchall())
    required = (
        "Index Scan using chemicals_pkey",
        "Index Scan using mols_pkey",
        "Index Scan using rdkit_mol_payload_queue_pkey",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"unsafe payload update plan missing {missing}:\n{text}")
    return text


def copy(batch_rows: int, rebuild_queue: bool) -> None:
    if free_bytes() < MIN_FREE_BYTES:
        raise RuntimeError("insufficient disk space before payload copy")
    conn = connect()
    try:
        build_queue(conn, rebuild_queue, batch_rows)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status,target_rows,copied_rows,last_chemical_id
                FROM pubchem.rdkit_mol_payload_meta WHERE singleton
                """
            )
            status, target, copied, last_id = cur.fetchone()
            target, copied, last_id = int(target), int(copied), int(last_id)
            if status == "complete":
                verify()
                return
            if status not in ("copying", "paused_space"):
                raise RuntimeError(f"unexpected payload state: {status}")
            plan = plan_guard(cur, last_id, batch_rows)
            print(plan, flush=True)
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_payload_meta
                SET status='copying',batch_rows=%s,updated_at=now()
                WHERE singleton
                """,
                (batch_rows,),
            )
        conn.commit()

        started = time.monotonic()
        session_start = copied
        while copied < target:
            available = free_bytes()
            if available < MIN_FREE_BYTES:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pubchem.rdkit_mol_payload_meta
                        SET status='paused_space',updated_at=now()
                        WHERE singleton
                        """
                    )
                conn.commit()
                raise RuntimeError(
                    f"payload copy paused at hard floor: "
                    f"{available / 1024**3:.2f} GiB free"
                )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH batch AS MATERIALIZED (
                        SELECT chemical_id,rdkit_mol_id
                        FROM pubchem.rdkit_mol_payload_queue
                        WHERE chemical_id > %s
                        ORDER BY chemical_id
                        LIMIT %s
                    ), updated AS MATERIALIZED (
                        UPDATE pubchem.chemicals AS c
                        SET mol=m.mol,
                            morgan_bfp=m.morgan_bfp,
                            morgan_sfp=m.morgan_sfp
                        FROM batch AS b
                        JOIN rdkit.mols AS m ON m.id=b.rdkit_mol_id
                        WHERE c.id=b.chemical_id
                          AND c.mol IS NULL
                          AND c.morgan_bfp IS NULL
                          AND c.morgan_sfp IS NULL
                        RETURNING c.id
                    )
                    SELECT (SELECT count(*) FROM batch),
                           (SELECT count(*) FROM updated),
                           (SELECT max(chemical_id) FROM batch)
                    """,
                    (last_id, batch_rows),
                )
                batch_count, updated_count, batch_last = cur.fetchone()
                batch_count = int(batch_count)
                updated_count = int(updated_count)
                if batch_count == 0:
                    raise RuntimeError("payload queue ended before target count")
                if updated_count != batch_count:
                    raise RuntimeError(
                        f"batch target was not empty: batch={batch_count}, "
                        f"updated={updated_count}, after chemical_id={last_id}"
                    )
                copied += updated_count
                last_id = int(batch_last)
                cur.execute(
                    """
                    UPDATE pubchem.rdkit_mol_payload_meta
                    SET copied_rows=%s,last_chemical_id=%s,updated_at=now()
                    WHERE singleton
                    """,
                    (copied, last_id),
                )
            conn.commit()
            elapsed = max(time.monotonic() - started, 0.001)
            rate = (copied - session_start) / elapsed
            print(
                f"copied={copied:,}/{target:,} chemical_id={last_id:,} "
                f"rate={rate:,.0f}/s free={free_bytes()/1024**3:.2f}GiB",
                flush=True,
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM (
                    SELECT chemical_id
                    FROM pubchem.rdkit_mol_payload_queue
                    ORDER BY chemical_id
                    LIMIT 1000
                ) AS q
                JOIN pubchem.chemicals AS c ON c.id=q.chemical_id
                WHERE c.mol IS NULL OR c.morgan_bfp IS NULL OR c.morgan_sfp IS NULL
                """
            )
            if int(cur.fetchone()[0]):
                raise RuntimeError("post-copy deterministic sample has missing payload")
            cur.execute(
                """
                UPDATE pubchem.rdkit_mol_payload_meta
                SET status='complete',updated_at=now(),completed_at=now()
                WHERE singleton
                """
            )
        conn.commit()
        verify()
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
                SELECT status,target_rows,copied_rows,last_chemical_id,batch_rows
                FROM pubchem.rdkit_mol_payload_meta WHERE singleton
                """
            )
            row = cur.fetchone()
            if row is None or row[0] != "complete":
                raise RuntimeError(f"payload copy is not complete: {row}")
            if int(row[1]) != EXPECTED_COPY_ROWS or int(row[2]) != EXPECTED_COPY_ROWS:
                raise RuntimeError(f"payload copy counts are invalid: {row}")
            result = {
                "status": row[0],
                "target_rows": row[1],
                "copied_rows": row[2],
                "last_chemical_id": row[3],
                "batch_rows": row[4],
                "free_gib": round(free_bytes() / 1024**3, 2),
            }
        conn.rollback()
        print(json.dumps(result, indent=2), flush=True)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("copy", "verify"))
    parser.add_argument("--batch-rows", type=int, default=DEFAULT_BATCH_ROWS)
    parser.add_argument("--rebuild-queue", action="store_true")
    args = parser.parse_args()
    if args.batch_rows < 1 or args.batch_rows > 50_000:
        raise SystemExit("--batch-rows must be between 1 and 50000")
    if args.action == "copy":
        copy(args.batch_rows, args.rebuild_queue)
    else:
        verify()


if __name__ == "__main__":
    main()
