#!/usr/bin/env python3
"""Materialize RDKit reaction objects for every parseable reaction SMILES.

The script converts in bounded ID batches, records failures, rebuilds the
partial GiST index once, and only then removes ORD's final legacy RDKit
reaction ID cache and compatibility view.
"""

from __future__ import annotations

import logging
import shutil
import sys
import time

import psycopg2


DB_NAME = "huagongshe"
BATCH_SIZE = 25_000
MIN_FREE_BYTES = 10 * 1024**3
LOCK_KEY = 7_219_240_721
EXPECTED_REACTIONS = 2_428_291
EXPECTED_SMILES = 2_418_635

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("materialize_rdkit_reactions")


def free_gib() -> float:
    return shutil.disk_usage("/").free / 1024**3


def require_disk(phase: str, floor_bytes: int = MIN_FREE_BYTES) -> None:
    free = shutil.disk_usage("/").free
    log.info("disk before %s: %.2f GiB free", phase, free / 1024**3)
    if free < floor_bytes:
        raise RuntimeError(
            f"disk guard stopped {phase}: {free / 1024**3:.2f} GiB free"
        )


def scalar(conn, sql: str, params: tuple = ()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def execute(conn, sql: str, params: tuple = ()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)


def set_meta(conn, key: str, value: str) -> None:
    execute(
        conn,
        """
        INSERT INTO public.reaction_rdkit_migration_meta(key,value,updated_at)
        VALUES (%s,%s,now())
        ON CONFLICT(key) DO UPDATE
          SET value=excluded.value,updated_at=excluded.updated_at
        """,
        (key, value),
    )


def get_meta(conn, key: str, default: str = "") -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM public.reaction_rdkit_migration_meta WHERE key=%s",
            (key,),
        )
        row = cur.fetchone()
        return row[0] if row else default


def bootstrap(conn) -> None:
    execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS public.reaction_rdkit_migration_meta(
          key text PRIMARY KEY,
          value text NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
    )
    execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS public.reaction_rdkit_failures(
          reaction_id bigint PRIMARY KEY REFERENCES public.reactions(id)
            ON DELETE CASCADE,
          reaction_smiles text NOT NULL,
          attempted_at timestamptz NOT NULL DEFAULT now()
        )
        """,
    )
    conn.commit()
    if not scalar(conn, "SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)):
        raise RuntimeError("another RDKit reaction migration holds the lock")
    execute(conn, "SET statement_timeout='0'")
    execute(conn, "SET lock_timeout='10s'")
    execute(conn, "SET idle_in_transaction_session_timeout='10min'")
    execute(conn, "SET maintenance_work_mem='256MB'")
    execute(conn, "SET work_mem='32MB'")
    execute(conn, "SET max_parallel_workers_per_gather=2")
    require_disk("bootstrap")

    reactions = scalar(conn, "SELECT count(*) FROM public.reactions")
    smiles = scalar(
        conn, "SELECT count(*) FROM public.reactions WHERE reaction_smiles IS NOT NULL"
    )
    if reactions != EXPECTED_REACTIONS or smiles != EXPECTED_SMILES:
        raise RuntimeError(
            f"reaction source changed: reactions={reactions}, smiles={smiles}"
        )
    execute(
        conn,
        """
        CREATE OR REPLACE FUNCTION pg_temp.try_reaction(input text)
        RETURNS public.reaction
        LANGUAGE plpgsql STRICT VOLATILE AS $$
        BEGIN
          RETURN input::public.reaction;
        EXCEPTION WHEN OTHERS THEN
          RETURN NULL;
        END;
        $$
        """,
    )
    conn.commit()


def drop_old_index(conn) -> None:
    if get_meta(conn, "old_index") == "removed":
        return
    execute(conn, "DROP INDEX IF EXISTS public.reactions_reaction_gist_idx")
    set_meta(conn, "old_index", "removed")
    conn.commit()


def convert(conn) -> None:
    if get_meta(conn, "conversion") == "complete":
        return
    last = int(get_meta(conn, "last_id", "0") or "0")
    max_id = scalar(conn, "SELECT max(id) FROM public.reactions")
    log.info("materializing reactions through id %d", max_id)
    while last < max_id:
        require_disk(f"RDKit reaction payload after id {last}")
        high = min(last + BATCH_SIZE, max_id)
        started = time.monotonic()
        fallback = False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.reactions
                    SET reaction=reaction_smiles::public.reaction,
                        updated_at=now()
                    WHERE id > %s AND id <= %s
                      AND reaction_smiles IS NOT NULL
                    """,
                    (last, high),
                )
                changed = cur.rowcount
        except Exception:
            conn.rollback()
            fallback = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.reactions
                    SET reaction=pg_temp.try_reaction(reaction_smiles),
                        updated_at=now()
                    WHERE id > %s AND id <= %s
                      AND reaction_smiles IS NOT NULL
                    """,
                    (last, high),
                )
                changed = cur.rowcount
        execute(
            conn,
            """
            INSERT INTO public.reaction_rdkit_failures(reaction_id,reaction_smiles)
            SELECT id,reaction_smiles FROM public.reactions
            WHERE id > %s AND id <= %s
              AND reaction_smiles IS NOT NULL AND reaction IS NULL
            ON CONFLICT(reaction_id) DO UPDATE
              SET reaction_smiles=excluded.reaction_smiles,attempted_at=now()
            """,
            (last, high),
        )
        set_meta(conn, "last_id", str(high))
        conn.commit()
        last = high
        if high % 250_000 == 0 or high == max_id:
            log.info(
                "through %d/%d changed=%d fallback=%s %.1fs disk=%.2fGiB",
                high,
                max_id,
                changed,
                fallback,
                time.monotonic() - started,
                free_gib(),
            )

    failures = scalar(conn, "SELECT count(*) FROM public.reaction_rdkit_failures")
    materialized = scalar(
        conn, "SELECT count(*) FROM public.reactions WHERE reaction IS NOT NULL"
    )
    if materialized + failures != EXPECTED_SMILES:
        raise RuntimeError(
            f"RDKit reaction coverage mismatch: parsed={materialized}, failures={failures}"
        )
    set_meta(conn, "conversion", "complete")
    set_meta(conn, "parsed", str(materialized))
    set_meta(conn, "failures", str(failures))
    conn.commit()
    log.info("conversion complete: parsed=%d failures=%d", materialized, failures)


def build_index(conn) -> None:
    if get_meta(conn, "gist_index") == "complete":
        return
    require_disk("full reaction GiST index", 12 * 1024**3)
    execute(
        conn,
        """
        CREATE INDEX reactions_reaction_gist_idx
          ON public.reactions USING gist(reaction)
          WHERE reaction IS NOT NULL
        """,
    )
    set_meta(conn, "gist_index", "complete")
    conn.commit()


def remove_legacy_rdkit(conn) -> None:
    if get_meta(conn, "legacy_rdkit") == "removed":
        return
    require_disk("legacy RDKit reaction removal")
    execute(
        conn,
        "ALTER TABLE ord.reaction DROP CONSTRAINT reaction_rdkit_reaction_id_fkey",
    )
    execute(conn, "DROP INDEX ord.ix_ord_reaction_rdkit_reaction_id")
    execute(conn, "DROP INDEX ord.reaction_unlinked_index")
    execute(conn, "ALTER TABLE ord.reaction DROP COLUMN rdkit_reaction_id")
    execute(conn, "DROP VIEW rdkit.reactions")
    execute(conn, "DROP TABLE ord.legacy_rdkit_reaction_map")
    set_meta(conn, "legacy_rdkit", "removed")
    conn.commit()
    execute(conn, "CHECKPOINT")


def finish(conn) -> None:
    conn.commit()
    previous_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("VACUUM (ANALYZE) public.reactions")
    finally:
        conn.autocommit = previous_autocommit
    parsed = scalar(conn, "SELECT count(*) FROM public.reactions WHERE reaction IS NOT NULL")
    failures = scalar(conn, "SELECT count(*) FROM public.reaction_rdkit_failures")
    log.info(
        "FINAL parsed=%d failures=%d disk=%.2fGiB", parsed, failures, free_gib()
    )


def main() -> int:
    conn = psycopg2.connect(dbname=DB_NAME, application_name="rdkit_reaction_materialization")
    conn.autocommit = False
    try:
        bootstrap(conn)
        drop_old_index(conn)
        convert(conn)
        build_index(conn)
        remove_legacy_rdkit(conn)
        finish(conn)
        return 0
    except Exception:
        conn.rollback()
        log.exception("materialization stopped safely")
        return 1
    finally:
        try:
            execute(conn, "SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            conn.commit()
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
