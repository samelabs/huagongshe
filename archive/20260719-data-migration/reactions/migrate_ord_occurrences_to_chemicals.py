#!/usr/bin/env python3
"""Replace ORD occurrence legacy Mol IDs with autonomous chemical IDs.

Run on the database host as PostgreSQL's OS user.  The service must remain
stopped.  The migration renames the existing column, removes only the legacy
index/FK, updates by primary-key ranges, validates new FKs, then removes the
compatibility views and bridge after both occurrence tables are complete.
"""

from __future__ import annotations

import logging
import shutil
import sys
import time

import psycopg2


DB_NAME = "huagongshe"
MIN_FREE_BYTES = 10 * 1024**3
BATCH_SIZE = 100_000
LOCK_KEY = 7_219_240_720

TABLES = {
    "compound": {
        "expected_rows": 17_043_157,
        "expected_linked": 16_242_914,
        "old_fk": "compound_rdkit_mol_id_fkey",
        "old_index": "ix_ord_compound_rdkit_mol_id",
        "new_index": "ix_ord_compound_chemical_id",
        "new_fk": "compound_chemical_id_fkey",
    },
    "product_compound": {
        "expected_rows": 2_673_037,
        "expected_linked": 2_605_008,
        "old_fk": "product_compound_rdkit_mol_id_fkey",
        "old_index": "ix_ord_product_compound_rdkit_mol_id",
        "new_index": "ix_ord_product_compound_chemical_id",
        "new_fk": "product_compound_chemical_id_fkey",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("migrate_ord_occurrences")


def free_gib() -> float:
    return shutil.disk_usage("/").free / 1024**3


def require_disk(phase: str) -> None:
    free = free_gib()
    log.info("disk before %s: %.2f GiB free", phase, free)
    if free * 1024**3 < MIN_FREE_BYTES:
        raise RuntimeError(f"disk guard stopped {phase}: {free:.2f} GiB free")


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
        INSERT INTO public.occurrence_chemical_migration_meta(key,value,updated_at)
        VALUES (%s,%s,now())
        ON CONFLICT(key) DO UPDATE
          SET value=excluded.value,updated_at=excluded.updated_at
        """,
        (key, value),
    )


def get_meta(conn, key: str, default: str = "") -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM public.occurrence_chemical_migration_meta WHERE key=%s",
            (key,),
        )
        row = cur.fetchone()
        return row[0] if row else default


def column_exists(conn, table: str, column: str) -> bool:
    return bool(
        scalar(
            conn,
            """
            SELECT EXISTS(
              SELECT 1 FROM information_schema.columns
              WHERE table_schema='ord' AND table_name=%s AND column_name=%s
            )
            """,
            (table, column),
        )
    )


def bootstrap(conn) -> None:
    execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS public.occurrence_chemical_migration_meta(
          key text PRIMARY KEY,
          value text NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
    )
    conn.commit()
    if not scalar(conn, "SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)):
        raise RuntimeError("another occurrence migration holds the advisory lock")
    execute(conn, "SET statement_timeout='0'")
    execute(conn, "SET lock_timeout='10s'")
    execute(conn, "SET idle_in_transaction_session_timeout='10min'")
    execute(conn, "SET maintenance_work_mem='256MB'")
    execute(conn, "SET work_mem='32MB'")
    require_disk("bootstrap")

    bridge_rows = scalar(conn, "SELECT count(*) FROM ord.legacy_rdkit_mol_map")
    bridge_chemicals = scalar(
        conn, "SELECT count(DISTINCT chemical_id) FROM ord.legacy_rdkit_mol_map"
    )
    if bridge_rows != 1_435_401 or bridge_chemicals != bridge_rows:
        raise RuntimeError(
            f"legacy Mol bridge is not one-to-one: rows={bridge_rows}, chemicals={bridge_chemicals}"
        )


def verify_source(conn, table: str, cfg: dict) -> None:
    rows = scalar(conn, f"SELECT count(*) FROM ord.{table}")
    old_column = "rdkit_mol_id" if column_exists(conn, table, "rdkit_mol_id") else "chemical_id"
    linked = scalar(conn, f"SELECT count({old_column}) FROM ord.{table}")
    if rows != cfg["expected_rows"] or linked != cfg["expected_linked"]:
        raise RuntimeError(
            f"{table} source count changed: rows={rows}, linked={linked}"
        )
    if old_column == "rdkit_mol_id":
        missing = scalar(
            conn,
            f"""
            SELECT count(*) FROM ord.{table} source
            LEFT JOIN ord.legacy_rdkit_mol_map mapping
              ON mapping.legacy_mol_id=source.rdkit_mol_id
            WHERE source.rdkit_mol_id IS NOT NULL
              AND mapping.legacy_mol_id IS NULL
            """,
        )
        if missing:
            raise RuntimeError(f"{table} has {missing} unmapped legacy Mol IDs")


def prepare_column(conn, table: str, cfg: dict) -> None:
    key = f"{table}_column"
    if get_meta(conn, key) == "prepared":
        return
    verify_source(conn, table, cfg)
    if column_exists(conn, table, "chemical_id"):
        raise RuntimeError(f"ord.{table}.chemical_id exists without migration marker")
    if not column_exists(conn, table, "rdkit_mol_id"):
        raise RuntimeError(f"ord.{table}.rdkit_mol_id is missing")

    log.info("preparing ord.%s chemical_id", table)
    execute(
        conn,
        f"ALTER TABLE ord.{table} DROP CONSTRAINT {cfg['old_fk']}",
    )
    execute(conn, f"DROP INDEX ord.{cfg['old_index']}")
    if table == "product_compound":
        execute(conn, "DROP INDEX ord.product_compound_unlinked_index")
    execute(
        conn,
        f"ALTER TABLE ord.{table} RENAME COLUMN rdkit_mol_id TO chemical_id",
    )
    set_meta(conn, key, "prepared")
    conn.commit()


def migrate_values(conn, table: str, cfg: dict) -> None:
    key = f"{table}_last_id"
    if get_meta(conn, f"{table}_values") == "complete":
        return
    last = int(get_meta(conn, key, "0") or "0")
    max_id = scalar(conn, f"SELECT max(id) FROM ord.{table}")
    log.info("migrating ord.%s through id %d", table, max_id)
    while last < max_id:
        require_disk(f"{table} values after id {last}")
        high = min(last + BATCH_SIZE, max_id)
        started = time.monotonic()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE ord.{table} target
                SET chemical_id=mapping.chemical_id
                FROM ord.legacy_rdkit_mol_map mapping
                WHERE target.id > %s AND target.id <= %s
                  AND target.chemical_id=mapping.legacy_mol_id
                  AND target.chemical_id IS DISTINCT FROM mapping.chemical_id
                """,
                (last, high),
            )
            changed = cur.rowcount
        set_meta(conn, key, str(high))
        conn.commit()
        last = high
        if high % 1_000_000 == 0 or high == max_id:
            log.info(
                "%s through %d/%d changed=%d %.2fs disk=%.2fGiB",
                table,
                high,
                max_id,
                changed,
                time.monotonic() - started,
                free_gib(),
            )

    linked = scalar(conn, f"SELECT count(chemical_id) FROM ord.{table}")
    missing = scalar(
        conn,
        f"""
        SELECT count(*) FROM ord.{table} source
        LEFT JOIN pubchem.chemicals chemical ON chemical.id=source.chemical_id
        WHERE source.chemical_id IS NOT NULL AND chemical.id IS NULL
        """,
    )
    if linked != cfg["expected_linked"] or missing:
        raise RuntimeError(
            f"{table} chemical validation failed: linked={linked}, missing={missing}"
        )
    set_meta(conn, f"{table}_values", "complete")
    conn.commit()


def create_constraints(conn, table: str, cfg: dict) -> None:
    if get_meta(conn, f"{table}_constraints") == "complete":
        return
    require_disk(f"{table} chemical index")
    execute(
        conn,
        f"CREATE INDEX {cfg['new_index']} ON ord.{table}(chemical_id)",
    )
    if table == "product_compound":
        execute(
            conn,
            """
            CREATE INDEX product_compound_unlinked_index
              ON ord.product_compound(reaction_outcome_id)
              WHERE chemical_id IS NULL
            """,
        )
    execute(
        conn,
        f"""
        ALTER TABLE ord.{table}
          ADD CONSTRAINT {cfg['new_fk']}
          FOREIGN KEY(chemical_id) REFERENCES pubchem.chemicals(id)
          ON DELETE RESTRICT NOT VALID
        """,
    )
    conn.commit()
    execute(
        conn,
        f"ALTER TABLE ord.{table} VALIDATE CONSTRAINT {cfg['new_fk']}",
    )
    execute(conn, f"ANALYZE ord.{table}")
    set_meta(conn, f"{table}_constraints", "complete")
    conn.commit()


def remove_bridge(conn) -> None:
    if get_meta(conn, "mol_bridge") == "removed":
        return
    for table in TABLES:
        if get_meta(conn, f"{table}_constraints") != "complete":
            raise RuntimeError("cannot remove Mol bridge before both tables validate")
    require_disk("Mol compatibility removal")
    if scalar(conn, "SELECT to_regclass('ord.mol_reaction') IS NOT NULL"):
        execute(conn, "DROP VIEW ord.mol_reaction")
    if scalar(conn, "SELECT to_regclass('rdkit.mols') IS NOT NULL"):
        execute(conn, "DROP VIEW rdkit.mols")
    execute(conn, "DROP TABLE ord.legacy_rdkit_mol_map")
    set_meta(conn, "mol_bridge", "removed")
    conn.commit()
    execute(conn, "CHECKPOINT")
    log.info("legacy Mol bridge and compatibility views removed")


def compact(conn) -> None:
    if get_meta(conn, "compaction") == "complete":
        return
    require_disk("ORD occurrence compaction")
    conn.commit()
    previous_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for table in TABLES:
                log.info("VACUUM FULL ANALYZE ord.%s", table)
                cur.execute(f"VACUUM (FULL, ANALYZE) ord.{table}")
    finally:
        conn.autocommit = previous_autocommit
    set_meta(conn, "compaction", "complete")
    conn.commit()
    execute(conn, "CHECKPOINT")


def final_report(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name,column_name
            FROM information_schema.columns
            WHERE table_schema='ord'
              AND table_name IN ('compound','product_compound')
              AND column_name IN ('chemical_id','rdkit_mol_id')
            ORDER BY table_name,column_name
            """
        )
        columns = cur.fetchall()
    if columns != [("compound", "chemical_id"), ("product_compound", "chemical_id")]:
        raise RuntimeError(f"unexpected occurrence columns: {columns}")
    log.info(
        "FINAL compound=%d product=%d disk=%.2fGiB",
        scalar(conn, "SELECT count(*) FROM ord.compound"),
        scalar(conn, "SELECT count(*) FROM ord.product_compound"),
        free_gib(),
    )


def main() -> int:
    conn = psycopg2.connect(dbname=DB_NAME, application_name="occurrence_chemical_migration")
    conn.autocommit = False
    try:
        bootstrap(conn)
        for table, cfg in TABLES.items():
            prepare_column(conn, table, cfg)
            migrate_values(conn, table, cfg)
            create_constraints(conn, table, cfg)
        remove_bridge(conn)
        compact(conn)
        final_report(conn)
        return 0
    except Exception:
        conn.rollback()
        log.exception("migration stopped safely")
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
