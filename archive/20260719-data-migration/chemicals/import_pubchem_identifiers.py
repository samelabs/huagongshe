#!/usr/bin/env python3
"""Validated, resumable import of selected PubChem external identifiers.

The input is streamed in CID order.  Six identifier arrays are updated together
so each affected chemicals row is rewritten only once.  A small temporary table
is reused for every batch; no full-size staging table is created.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg2


SOURCE = Path("/var/www/ord-samelabs/CID-Identifiers.tsv.gz")
EXPECTED_SHA256 = "e2678a1cf8df953d1d18a99bd5476153b416b1cebfe25ffc6a7c58a504ada987"
EXPECTED_SOURCE_ROWS = 12_742_769
EXPECTED_RAW = {
    "cas_numbers": 1_460_262,
    "nikkaji_numbers": 3_584_326,
    "chembl_ids": 2_925_893,
    "ec_numbers": 355_718,
    "unii_codes": 125_565,
    "chebi_ids": 179_537,
}
EXPECTED_ACCEPTED = {
    "cas_numbers": 1_460_132,
    "nikkaji_numbers": 3_584_326,
    "chembl_ids": 2_925_893,
    "ec_numbers": 355_718,
    "unii_codes": 125_565,
    "chebi_ids": 179_537,
}
DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
BATCH_CIDS = int(os.environ.get("PUBCHEM_IDENTIFIER_BATCH_CIDS", "50000"))
MIN_LOAD_FREE_BYTES = 5 * 1024**3
MIN_INDEX_FREE_BYTES = 6 * 1024**3
MAX_WAL_BYTES = 3 * 1024**3

TYPE_TO_COLUMN = {
    "CAS": "cas_numbers",
    "Nikkaji Number": "nikkaji_numbers",
    "ChEMBL ID": "chembl_ids",
    "European Community (EC) Number": "ec_numbers",
    "UNII": "unii_codes",
    "ChEBI ID": "chebi_ids",
}
COLUMNS = tuple(EXPECTED_RAW)
PATTERNS = {
    "cas_numbers": re.compile(r"^[1-9][0-9]{1,6}-[0-9]{2}-[0-9]$"),
    "nikkaji_numbers": re.compile(r"^J[0-9A-Z.]+$"),
    "chembl_ids": re.compile(r"^CHEMBL[0-9]+$"),
    "ec_numbers": re.compile(r"^[0-9]{3}-[0-9]{3}-[0-9]$"),
    "unii_codes": re.compile(r"^[0-9A-Z]{10}$"),
    "chebi_ids": re.compile(r"^CHEBI:[0-9]+$"),
}


def connect(*, autocommit: bool = False):
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = autocommit
    with conn.cursor() as cur:
        cur.execute("SET application_name = 'pubchem_identifier_import'")
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET lock_timeout = '30s'")
        cur.execute("SET wal_compression = on")
    if not autocommit:
        conn.commit()
    return conn


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cas_checksum_valid(value: str) -> bool:
    digits = value.replace("-", "")
    expected = int(digits[-1])
    actual = sum(
        multiplier * int(digit)
        for multiplier, digit in enumerate(reversed(digits[:-1]), 1)
    ) % 10
    return actual == expected


def validate_value(column: str, value: str) -> tuple[bool, str | None]:
    if not PATTERNS[column].fullmatch(value):
        return False, "invalid_format"
    if column == "cas_numbers" and not cas_checksum_valid(value):
        return False, "invalid_checksum"
    return True, None


def source_records():
    """Yield parsed input and enforce global CID ordering and three columns."""
    previous_cid = 0
    with gzip.open(SOURCE, "rt", encoding="utf-8", newline="") as src:
        for line_number, line in enumerate(src, 1):
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) != 3:
                raise ValueError(
                    f"source line {line_number} has {len(parts)} columns, expected 3"
                )
            cid_text, value, identifier_type = parts
            try:
                cid = int(cid_text)
            except ValueError as exc:
                raise ValueError(f"invalid CID at source line {line_number}") from exc
            if cid < previous_cid:
                raise ValueError(
                    f"CID order violation at source line {line_number}: "
                    f"{cid} < {previous_cid}"
                )
            previous_cid = cid
            yield line_number, cid, value, identifier_type


def _empty_values() -> dict[str, set[str]]:
    return {column: set() for column in COLUMNS}


def preflight(*, quiet: bool = False) -> dict:
    source_hash = sha256_file(SOURCE)
    if source_hash != EXPECTED_SHA256:
        raise RuntimeError(
            f"source SHA256 mismatch: expected {EXPECTED_SHA256}, got {source_hash}"
        )

    raw = Counter()
    accepted = Counter()
    rejected = Counter()
    nonnull_cids = Counter()
    multivalue_cids = Counter()
    max_values_per_cid = Counter()
    affected_cids = 0
    total_lines = 0
    current_cid: int | None = None
    current = _empty_values()

    def finalize() -> None:
        nonlocal affected_cids
        if current_cid is None:
            return
        if any(current.values()):
            affected_cids += 1
        for column, values in current.items():
            count = len(values)
            if count:
                nonnull_cids[column] += 1
                max_values_per_cid[column] = max(max_values_per_cid[column], count)
                if count > 1:
                    multivalue_cids[column] += 1

    for line_number, cid, value, identifier_type in source_records():
        total_lines = line_number
        if current_cid != cid:
            finalize()
            current_cid = cid
            current = _empty_values()
        column = TYPE_TO_COLUMN.get(identifier_type)
        if column is None:
            continue
        raw[column] += 1
        valid, reason = validate_value(column, value)
        if not valid:
            if column != "cas_numbers":
                raise ValueError(
                    f"unexpected invalid {column} value at line {line_number}: {value!r}"
                )
            rejected[reason or "invalid"] += 1
            continue
        if value in current[column]:
            raise ValueError(
                f"duplicate ({cid}, {identifier_type}, {value}) at line {line_number}"
            )
        current[column].add(value)
        accepted[column] += 1
    finalize()

    if total_lines != EXPECTED_SOURCE_ROWS:
        raise RuntimeError(
            f"source row mismatch: expected {EXPECTED_SOURCE_ROWS}, got {total_lines}"
        )
    if dict(raw) != EXPECTED_RAW:
        raise RuntimeError(f"raw count mismatch: expected {EXPECTED_RAW}, got {dict(raw)}")
    if dict(accepted) != EXPECTED_ACCEPTED:
        raise RuntimeError(
            f"accepted count mismatch: expected {EXPECTED_ACCEPTED}, got {dict(accepted)}"
        )
    if sum(rejected.values()) != 130:
        raise RuntimeError(f"CAS rejection mismatch: expected 130, got {dict(rejected)}")

    manifest = {
        "source_sha256": source_hash,
        "source_rows": total_lines,
        "raw_values": {column: raw[column] for column in COLUMNS},
        "accepted_values": {column: accepted[column] for column in COLUMNS},
        "rejected_values": dict(sorted(rejected.items())),
        "nonnull_cids": {column: nonnull_cids[column] for column in COLUMNS},
        "multivalue_cids": {
            column: multivalue_cids[column] for column in COLUMNS
        },
        "max_values_per_cid": {
            column: max_values_per_cid[column] for column in COLUMNS
        },
        "affected_cids": affected_cids,
        "accepted_total": sum(accepted.values()),
    }
    if not quiet:
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return manifest


def disk_free_bytes() -> int:
    return shutil.disk_usage("/").free


def wal_bytes(cur) -> int:
    cur.execute("SELECT coalesce(sum(size), 0)::bigint FROM pg_ls_waldir()")
    return int(cur.fetchone()[0])


def gib(value: int) -> float:
    return value / 1024**3


def enforce_space(cur, minimum: int = MIN_LOAD_FREE_BYTES) -> tuple[int, int]:
    free = disk_free_bytes()
    wal = wal_bytes(cur)
    if free < minimum:
        raise RuntimeError(
            f"disk safety stop: free={gib(free):.2f}GiB, "
            f"required={gib(minimum):.2f}GiB"
        )
    if wal > MAX_WAL_BYTES:
        raise RuntimeError(
            f"WAL safety stop: pg_wal={gib(wal):.2f}GiB, "
            f"limit={gib(MAX_WAL_BYTES):.2f}GiB"
        )
    return free, wal


def self_test() -> None:
    assert cas_checksum_valid("50-00-0")
    assert not cas_checksum_valid("58-89-2")
    assert validate_value("nikkaji_numbers", "J1.808.087G")[0]
    assert validate_value("chembl_ids", "CHEMBL25")[0]
    assert validate_value("ec_numbers", "200-001-8")[0]
    assert validate_value("unii_codes", "07OP6H4V4A")[0]
    assert validate_value("chebi_ids", "CHEBI:15377")[0]

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE identifier_copy_test "
                "(pubchem_cid integer, cas_numbers text[], nikkaji_numbers text[], "
                "chembl_ids text[], ec_numbers text[], unii_codes text[], "
                "chebi_ids text[])"
            )
            rows = [
                (
                    1,
                    ["50-00-0"],
                    ["J1.2A", "J2.3B"],
                    None,
                    ["200-001-8"],
                    ["07OP6H4V4A"],
                    ["CHEBI:15377"],
                )
            ]
            cur.copy_expert(
                stage_copy_sql("identifier_copy_test"), encode_rows(rows)
            )
            cur.execute("SELECT * FROM identifier_copy_test")
            copied = cur.fetchone()
        conn.rollback()
    finally:
        conn.close()
    assert copied == tuple(rows[0])
    print("self-test passed: validation and PostgreSQL array COPY", flush=True)


def prepare() -> dict:
    manifest = preflight(quiet=True)
    if disk_free_bytes() < 8 * 1024**3:
        raise RuntimeError("prepare requires at least 8GiB free")
    conn = connect()
    try:
        with conn.cursor() as cur:
            enforce_space(cur)
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid='pubchem.chemicals'::regclass
                      AND attname='cas' AND NOT attisdropped
                )
                """
            )
            if cur.fetchone()[0]:
                cur.execute(
                    "SELECT count(*) FROM pubchem.chemicals WHERE cas IS NOT NULL"
                )
                if cur.fetchone()[0] != 0:
                    raise RuntimeError("existing scalar cas column is not empty")
                cur.execute("ALTER TABLE pubchem.chemicals DROP COLUMN cas")
            for column in COLUMNS:
                cur.execute(
                    f"ALTER TABLE pubchem.chemicals "
                    f"ADD COLUMN IF NOT EXISTS {column} text[]"
                )
            cur.execute(
                """
                SELECT attname, format_type(atttypid, atttypmod)
                FROM pg_attribute
                WHERE attrelid='pubchem.chemicals'::regclass
                  AND attname = ANY(%s) AND NOT attisdropped
                ORDER BY attname
                """,
                (list(COLUMNS),),
            )
            actual_types = dict(cur.fetchall())
            expected_types = {column: "text[]" for column in COLUMNS}
            if actual_types != expected_types:
                raise RuntimeError(
                    f"identifier column type mismatch: {actual_types}"
                )
            cur.execute(
                """
                ALTER TABLE pubchem.chemicals_import_meta
                    ADD COLUMN IF NOT EXISTS identifiers_source_path text,
                    ADD COLUMN IF NOT EXISTS identifiers_source_sha256 text,
                    ADD COLUMN IF NOT EXISTS identifiers_expected_counts jsonb,
                    ADD COLUMN IF NOT EXISTS identifiers_loaded_cids bigint NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS identifiers_loaded_values bigint NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS identifiers_orphan_cids bigint NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS identifiers_orphan_values bigint NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS identifiers_orphan_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
                    ADD COLUMN IF NOT EXISTS identifiers_orphan_nonnull_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
                    ADD COLUMN IF NOT EXISTS identifiers_orphan_samples jsonb NOT NULL DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS identifiers_last_cid integer NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS identifiers_status text,
                    ADD COLUMN IF NOT EXISTS identifiers_started_at timestamptz,
                    ADD COLUMN IF NOT EXISTS identifiers_updated_at timestamptz,
                    ADD COLUMN IF NOT EXISTS identifiers_completed_at timestamptz,
                    ADD COLUMN IF NOT EXISTS identifiers_rejected_counts jsonb
                """
            )
            cur.execute(
                """
                SELECT identifiers_status, identifiers_source_sha256
                FROM pubchem.chemicals_import_meta WHERE singleton
                """
            )
            status, existing_hash = cur.fetchone()
            if status is not None and existing_hash != EXPECTED_SHA256:
                raise RuntimeError(
                    f"existing identifier import uses different SHA256: {existing_hash}"
                )
            if status is None:
                cur.execute(
                    """
                    UPDATE pubchem.chemicals_import_meta
                    SET identifiers_source_path=%s,
                        identifiers_source_sha256=%s,
                        identifiers_expected_counts=%s::jsonb,
                        identifiers_loaded_cids=0,
                        identifiers_loaded_values=0,
                        identifiers_orphan_cids=0,
                        identifiers_orphan_values=0,
                        identifiers_orphan_counts='{}'::jsonb,
                        identifiers_orphan_nonnull_counts='{}'::jsonb,
                        identifiers_orphan_samples='[]'::jsonb,
                        identifiers_last_cid=0,
                        identifiers_status='prepared',
                        identifiers_started_at=now(),
                        identifiers_updated_at=now(),
                        identifiers_rejected_counts=%s::jsonb
                    WHERE singleton
                    """,
                    (
                        str(SOURCE),
                        EXPECTED_SHA256,
                        json.dumps(manifest, sort_keys=True),
                        json.dumps(manifest["rejected_values"], sort_keys=True),
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(
        "schema prepared: cas_numbers plus five identifier arrays; "
        f"affected_cids={manifest['affected_cids']:,}",
        flush=True,
    )
    return manifest


def iter_grouped(after_cid: int = 0):
    current_cid: int | None = None
    current = _empty_values()

    def emit():
        if current_cid is None or current_cid <= after_cid or not any(current.values()):
            return None
        return (
            current_cid,
            *(
                sorted(current[column]) if current[column] else None
                for column in COLUMNS
            ),
        )

    for line_number, cid, value, identifier_type in source_records():
        if current_cid != cid:
            row = emit()
            if row is not None:
                yield row
            current_cid = cid
            current = _empty_values()
        column = TYPE_TO_COLUMN.get(identifier_type)
        if column is None:
            continue
        valid, reason = validate_value(column, value)
        if not valid:
            if column != "cas_numbers":
                raise ValueError(
                    f"unexpected invalid {column} value at line {line_number}: {value!r}"
                )
            continue
        if value in current[column]:
            raise ValueError(
                f"duplicate ({cid}, {identifier_type}, {value}) at line {line_number}"
            )
        current[column].add(value)
    row = emit()
    if row is not None:
        yield row


def pg_array(values: list[str] | None) -> str | None:
    if values is None:
        return None
    escaped = [
        '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        for value in values
    ]
    return "{" + ",".join(escaped) + "}"


def encode_rows(rows) -> io.StringIO:
    buf = io.StringIO()
    writer = csv.writer(
        buf,
        delimiter="\t",
        quotechar='"',
        doublequote=True,
        lineterminator="\n",
    )
    for row in rows:
        writer.writerow([row[0], *(pg_array(value) for value in row[1:])])
    buf.seek(0)
    return buf


def stage_copy_sql(table: str = "identifiers_stage") -> str:
    return f"""
        COPY {table} (pubchem_cid, {', '.join(COLUMNS)})
        FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', QUOTE E'\"', ESCAPE E'\"')
    """


def create_stage(cur) -> None:
    cur.execute(
        f"""
        CREATE TEMP TABLE identifiers_stage (
            pubchem_cid integer PRIMARY KEY,
            {', '.join(column + ' text[]' for column in COLUMNS)}
        ) ON COMMIT PRESERVE ROWS
        """
    )


def mark_interrupted() -> None:
    try:
        conn = connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pubchem.chemicals_import_meta
                SET identifiers_status='interrupted', identifiers_updated_at=now()
                WHERE singleton AND identifiers_status <> 'complete'
                """
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"warning: could not mark interrupted: {exc}", file=sys.stderr)


def load() -> None:
    conn = connect()
    started = time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT identifiers_status, identifiers_source_sha256,
                       identifiers_loaded_cids, identifiers_loaded_values,
                       identifiers_orphan_cids, identifiers_orphan_values,
                       identifiers_orphan_counts,
                       identifiers_orphan_nonnull_counts,
                       identifiers_orphan_samples,
                       identifiers_last_cid, identifiers_expected_counts
                FROM pubchem.chemicals_import_meta WHERE singleton
                """
            )
            state = cur.fetchone()
        if state is None or state[0] is None:
            raise RuntimeError("identifier import is not prepared")
        (
            status,
            source_hash,
            loaded_cids,
            loaded_values,
            orphan_cids,
            orphan_values,
            orphan_counts,
            orphan_nonnull_counts,
            orphan_samples,
            last_cid,
            manifest,
        ) = state
        if source_hash != EXPECTED_SHA256:
            raise RuntimeError("prepared source SHA256 does not match this importer")
        if status == "complete":
            print("identifier import already complete", flush=True)
            return
        if sha256_file(SOURCE) != EXPECTED_SHA256:
            raise RuntimeError("source changed after prepare")

        with conn.cursor() as cur:
            create_stage(cur)
            cur.execute(
                """
                UPDATE pubchem.chemicals_import_meta
                SET identifiers_status='loading', identifiers_updated_at=now()
                WHERE singleton
                """
            )
        conn.commit()

        initial_processed = loaded_cids + orphan_cids
        batch = []
        for row in iter_grouped(after_cid=last_cid):
            batch.append(row)
            if len(batch) >= BATCH_CIDS:
                (
                    loaded_cids,
                    loaded_values,
                    orphan_cids,
                    orphan_values,
                    orphan_counts,
                    orphan_nonnull_counts,
                    orphan_samples,
                    last_cid,
                ) = commit_batch(
                    conn,
                    batch,
                    loaded_cids,
                    loaded_values,
                    orphan_cids,
                    orphan_values,
                    orphan_counts,
                    orphan_nonnull_counts,
                    orphan_samples,
                )
                batch.clear()
                report_progress(
                    started,
                    initial_processed,
                    loaded_cids,
                    loaded_values,
                    orphan_cids,
                    orphan_values,
                    last_cid,
                    manifest,
                )
        if batch:
            (
                loaded_cids,
                loaded_values,
                orphan_cids,
                orphan_values,
                orphan_counts,
                orphan_nonnull_counts,
                orphan_samples,
                last_cid,
            ) = commit_batch(
                conn,
                batch,
                loaded_cids,
                loaded_values,
                orphan_cids,
                orphan_values,
                orphan_counts,
                orphan_nonnull_counts,
                orphan_samples,
            )
            report_progress(
                started,
                initial_processed,
                loaded_cids,
                loaded_values,
                orphan_cids,
                orphan_values,
                last_cid,
                manifest,
            )

        if loaded_cids + orphan_cids != manifest["affected_cids"]:
            raise RuntimeError(
                f"processed CID mismatch: expected {manifest['affected_cids']}, "
                f"got loaded={loaded_cids} orphan={orphan_cids}"
            )
        if loaded_values + orphan_values != manifest["accepted_total"]:
            raise RuntimeError(
                f"processed value mismatch: expected {manifest['accepted_total']}, "
                f"got loaded={loaded_values} orphan={orphan_values}"
            )
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pubchem.chemicals_import_meta
                SET identifiers_status='loaded', identifiers_updated_at=now()
                WHERE singleton
                """
            )
        conn.commit()
        print(
            f"LOAD COMPLETE cids={loaded_cids:,} values={loaded_values:,} "
            f"orphan_cids={orphan_cids:,} orphan_values={orphan_values:,} "
            f"elapsed={time.monotonic()-started:.1f}s",
            flush=True,
        )
    except Exception:
        conn.rollback()
        conn.close()
        mark_interrupted()
        raise
    else:
        conn.close()


def commit_batch(
    conn,
    rows,
    loaded_cids: int,
    loaded_values: int,
    orphan_cids: int,
    orphan_values: int,
    orphan_counts: dict,
    orphan_nonnull_counts: dict,
    orphan_samples: list,
):
    batch_values = sum(
        len(values) for row in rows for values in row[1:] if values is not None
    )
    batch_last_cid = rows[-1][0]
    try:
        with conn.cursor() as cur:
            enforce_space(cur)
            cur.execute("TRUNCATE identifiers_stage")
            cur.copy_expert(stage_copy_sql(), encode_rows(rows))
            cur.execute(
                """
                SELECT s.pubchem_cid
                FROM identifiers_stage AS s
                LEFT JOIN pubchem.chemicals AS c USING (pubchem_cid)
                WHERE c.pubchem_cid IS NULL
                ORDER BY s.pubchem_cid
                """
            )
            missing_ids = {int(row[0]) for row in cur.fetchall()}
            batch_orphan_counts = Counter()
            batch_orphan_nonnull = Counter()
            batch_orphan_values = 0
            if missing_ids:
                rows_by_cid = {row[0]: row for row in rows}
                for missing_cid in missing_ids:
                    missing_row = rows_by_cid[missing_cid]
                    for column, values in zip(COLUMNS, missing_row[1:]):
                        if values is not None:
                            batch_orphan_nonnull[column] += 1
                            batch_orphan_counts[column] += len(values)
                            batch_orphan_values += len(values)
                for column in COLUMNS:
                    orphan_counts[column] = (
                        int(orphan_counts.get(column, 0))
                        + batch_orphan_counts[column]
                    )
                    orphan_nonnull_counts[column] = (
                        int(orphan_nonnull_counts.get(column, 0))
                        + batch_orphan_nonnull[column]
                    )
                for missing_cid in sorted(missing_ids):
                    if missing_cid not in orphan_samples and len(orphan_samples) < 100:
                        orphan_samples.append(missing_cid)
                print(
                    f"ORPHAN source CIDs skipped: {sorted(missing_ids)} "
                    f"values={batch_orphan_values}",
                    flush=True,
                )
            assignments = ", ".join(
                f"{column}=s.{column}" for column in COLUMNS
            )
            cur.execute(
                f"""
                UPDATE pubchem.chemicals AS c
                SET {assignments}
                FROM identifiers_stage AS s
                WHERE c.pubchem_cid=s.pubchem_cid
                  AND c.pubchem_cid BETWEEN %s AND %s
                """,
                (rows[0][0], rows[-1][0]),
            )
            updated_rows = len(rows) - len(missing_ids)
            if cur.rowcount != updated_rows:
                raise RuntimeError(
                    f"target CID mismatch in batch {rows[0][0]}..{rows[-1][0]}: "
                    f"expected {updated_rows} updates after {len(missing_ids)} "
                    f"known orphans, got {cur.rowcount}"
                )
            batch_loaded_values = batch_values - batch_orphan_values
            cur.execute(
                """
                UPDATE pubchem.chemicals_import_meta SET
                    identifiers_loaded_cids=%s,
                    identifiers_loaded_values=%s,
                    identifiers_orphan_cids=%s,
                    identifiers_orphan_values=%s,
                    identifiers_orphan_counts=%s::jsonb,
                    identifiers_orphan_nonnull_counts=%s::jsonb,
                    identifiers_orphan_samples=%s::jsonb,
                    identifiers_last_cid=%s,
                    identifiers_status='loading',
                    identifiers_updated_at=now()
                WHERE singleton
                """,
                (
                    loaded_cids + updated_rows,
                    loaded_values + batch_loaded_values,
                    orphan_cids + len(missing_ids),
                    orphan_values + batch_orphan_values,
                    json.dumps(orphan_counts, sort_keys=True),
                    json.dumps(orphan_nonnull_counts, sort_keys=True),
                    json.dumps(orphan_samples),
                    batch_last_cid,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return (
        loaded_cids + updated_rows,
        loaded_values + batch_loaded_values,
        orphan_cids + len(missing_ids),
        orphan_values + batch_orphan_values,
        orphan_counts,
        orphan_nonnull_counts,
        orphan_samples,
        batch_last_cid,
    )


def report_progress(
    started,
    initial_processed,
    loaded_cids,
    loaded_values,
    orphan_cids,
    orphan_values,
    last_cid,
    manifest,
):
    elapsed = max(time.monotonic() - started, 0.001)
    processed_cids = loaded_cids + orphan_cids
    rate = (processed_cids - initial_processed) / elapsed
    remaining = manifest["affected_cids"] - processed_cids
    eta = remaining / rate if rate > 0 else 0
    print(
        f"cids={loaded_cids:,}+{orphan_cids:,}/{manifest['affected_cids']:,} "
        f"values={loaded_values:,}+{orphan_values:,}/{manifest['accepted_total']:,} "
        f"last_cid={last_cid:,} rate={rate:,.0f}/s eta={eta/3600:.2f}h "
        f"free={gib(disk_free_bytes()):.2f}GiB",
        flush=True,
    )


def vacuum_analyze() -> None:
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            print("VACUUM (ANALYZE) pubchem.chemicals", flush=True)
            cur.execute("VACUUM (ANALYZE) pubchem.chemicals")
    finally:
        conn.close()


def verify() -> None:
    if sha256_file(SOURCE) != EXPECTED_SHA256:
        raise RuntimeError("source SHA256 changed before verification")
    conn = connect()
    try:
        with conn.cursor() as cur:
            enforce_space(cur)
            cur.execute(
                """
                SELECT identifiers_expected_counts, expected_rows,
                       canonicalized_rows, failed_rows, identifiers_status,
                       identifiers_orphan_counts,
                       identifiers_orphan_nonnull_counts
                FROM pubchem.chemicals_import_meta WHERE singleton
                """
            )
            (
                manifest,
                expected_rows,
                expected_smiles,
                expected_failed,
                status,
                orphan_counts,
                orphan_nonnull_counts,
            ) = cur.fetchone()
            if status not in ("loaded", "verified", "complete"):
                raise RuntimeError(f"cannot verify identifier status {status!r}")
            aggregates = ["count(*)", "count(smiles)", "count(*)-count(smiles)"]
            for column in COLUMNS:
                aggregates.extend(
                    [
                        f"count({column})",
                        f"coalesce(sum(cardinality({column})), 0)",
                    ]
                )
            cur.execute(f"SELECT {', '.join(aggregates)} FROM pubchem.chemicals")
            result = cur.fetchone()
            if result[:3] != (expected_rows, expected_smiles, expected_failed):
                raise RuntimeError(
                    "base chemicals counts changed: "
                    f"expected {(expected_rows, expected_smiles, expected_failed)}, "
                    f"got {result[:3]}"
                )
            offset = 3
            actual = {}
            for column in COLUMNS:
                actual[column] = {
                    "nonnull_cids": int(result[offset]),
                    "accepted_values": int(result[offset + 1]),
                }
                offset += 2
            for column in COLUMNS:
                expected_pair = (
                    manifest["nonnull_cids"][column]
                    - int(orphan_nonnull_counts.get(column, 0)),
                    manifest["accepted_values"][column]
                    - int(orphan_counts.get(column, 0)),
                )
                actual_pair = (
                    actual[column]["nonnull_cids"],
                    actual[column]["accepted_values"],
                )
                if actual_pair != expected_pair:
                    raise RuntimeError(
                        f"verification mismatch for {column}: "
                        f"expected {expected_pair}, got {actual_pair}"
                    )
            cur.execute(
                """
                UPDATE pubchem.chemicals_import_meta
                SET identifiers_status='verified', identifiers_updated_at=now()
                WHERE singleton
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(
        "VERIFIED base counts unchanged and all six identifier counts exact: "
        + json.dumps(actual, sort_keys=True),
        flush=True,
    )


def build_index() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            free, wal = enforce_space(cur, MIN_INDEX_FREE_BYTES)
            cur.execute(
                "SELECT identifiers_status FROM pubchem.chemicals_import_meta "
                "WHERE singleton"
            )
            status = cur.fetchone()[0]
            if status not in ("verified", "complete"):
                raise RuntimeError(f"cannot build index at status {status!r}")
            cur.execute("SET maintenance_work_mem = '256MB'")
            print(
                f"building combined GIN index; free={gib(free):.2f}GiB "
                f"wal={gib(wal):.2f}GiB",
                flush=True,
            )
            predicate = " OR ".join(f"{column} IS NOT NULL" for column in COLUMNS)
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS chemicals_identifiers_gin
                ON pubchem.chemicals USING gin ({', '.join(COLUMNS)})
                WHERE {predicate}
                """
            )
            for column in COLUMNS:
                cur.execute(
                    f"ALTER TABLE pubchem.chemicals "
                    f"ALTER COLUMN {column} SET STATISTICS 500"
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("ANALYZE pubchem.chemicals")
    finally:
        conn.close()

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_relation_size('pubchem.chemicals_identifiers_gin')"
            )
            index_bytes = int(cur.fetchone()[0])
            for column in COLUMNS:
                cur.execute(
                    f"SELECT {column}[1] FROM pubchem.chemicals "
                    f"WHERE {column} IS NOT NULL LIMIT 1"
                )
                value = cur.fetchone()[0]
                cur.execute(
                    f"EXPLAIN (FORMAT JSON) SELECT pubchem_cid "
                    f"FROM pubchem.chemicals WHERE {column} @> ARRAY[%s]",
                    (value,),
                )
                plan_text = json.dumps(cur.fetchone()[0])
                if "chemicals_identifiers_gin" not in plan_text:
                    raise RuntimeError(f"GIN index not selected for {column}")
            cur.execute(
                """
                UPDATE pubchem.chemicals_import_meta
                SET identifiers_status='complete',
                    identifiers_completed_at=now(), identifiers_updated_at=now()
                WHERE singleton
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(
        f"INDEX VERIFIED chemicals_identifiers_gin size={gib(index_bytes):.2f}GiB",
        flush=True,
    )


def status() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT identifiers_status, identifiers_loaded_cids,
                       identifiers_loaded_values, identifiers_orphan_cids,
                       identifiers_orphan_values, identifiers_orphan_samples,
                       identifiers_last_cid,
                       identifiers_started_at, identifiers_updated_at,
                       identifiers_completed_at
                FROM pubchem.chemicals_import_meta WHERE singleton
                """
            )
            print(cur.fetchone())
            free, wal = enforce_space(cur)
            print(f"free={gib(free):.2f}GiB pg_wal={gib(wal):.2f}GiB")
    finally:
        conn.close()


def run_all() -> None:
    self_test()
    prepare()
    load()
    vacuum_analyze()
    verify()
    build_index()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "self-test",
            "preflight",
            "prepare",
            "load",
            "vacuum",
            "verify",
            "index",
            "status",
            "all",
        ),
    )
    args = parser.parse_args()
    actions = {
        "self-test": self_test,
        "preflight": preflight,
        "prepare": prepare,
        "load": load,
        "vacuum": vacuum_analyze,
        "verify": verify,
        "index": build_index,
        "status": status,
        "all": run_all,
    }
    actions[args.action]()


if __name__ == "__main__":
    main()
