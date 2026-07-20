#!/usr/bin/env python3
"""Attach verified DSSTox records to pubchem.chemicals.

The import is deliberately structure-strict:

* CAS is only used to find a small candidate set through the existing GIN index.
* A row is accepted only when exactly one candidate agrees by canonical SMILES
  or full standard InChIKey.
* If multiple DSSTox substances resolve to one chemical, all of them are held
  back instead of forcing a scalar DTXSID to represent a many-to-one conflict.
* Formula, masses and InChIKey are calculated once from the accepted chemicals
  SMILES, so the materialized display fields agree with the canonical structure.

Matching results are kept in a small unlogged table.  Both matching and applying
are resumable, while the 124M-row chemicals table is updated only once per match.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import Descriptors, rdMolDescriptors


SOURCE = Path("/var/www/ord-samelabs/DSSToxCCDdump.csv")
EXPECTED_SHA256 = "e69f56b35ce9d626810c6df2b5c79c48d0c3bb50ccde399da30687c6dd6d6a1b"
EXPECTED_ROWS = 1_246_399
EXPECTED_HEADER = [
    "DTXSID",
    "PREFERRED_NAME",
    "CASRN",
    "DTXCID",
    "INCHIKEY",
    "IUPAC_NAME",
    "SMILES",
    "MOLECULAR_FORMULA",
    "AVERAGE_MASS",
    "MONOISOTOPIC_MASS",
    "QSAR_READY_SMILES",
    "MS_READY_SMILES",
    "IDENTIFIER",
]
DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
BATCH_ROWS = int(os.environ.get("DSSTOX_BATCH_ROWS", "5000"))
APPLY_ROWS = int(os.environ.get("DSSTOX_APPLY_ROWS", "10000"))
MIN_FREE_BYTES = int(os.environ.get("DSSTOX_MIN_FREE_BYTES", str(5 * 1024**3)))

CAS_RE = re.compile(r"^[1-9][0-9]{1,6}-[0-9]{2}-[0-9]$")
DTXSID_RE = re.compile(r"^DTXSID[0-9]+$")
INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")

RDLogger.DisableLog("rdApp.*")
csv.field_size_limit(16 * 1024 * 1024)


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def connect(*, autocommit: bool = False):
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = autocommit
    with conn.cursor() as cur:
        cur.execute("SET application_name = 'dsstox_chemicals_import'")
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET lock_timeout = '30s'")
        cur.execute("SET wal_compression = on")
        cur.execute("SET synchronous_commit = off")
    if not autocommit:
        conn.commit()
    return conn


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def free_bytes() -> int:
    return shutil.disk_usage("/").free


def require_disk() -> None:
    available = free_bytes()
    if available < MIN_FREE_BYTES:
        raise RuntimeError(
            f"disk guard: {available / 1024**3:.2f} GiB free, "
            f"minimum is {MIN_FREE_BYTES / 1024**3:.2f} GiB"
        )


def cas_valid(value: str) -> bool:
    if not CAS_RE.fullmatch(value):
        return False
    digits = value.replace("-", "")
    checksum = sum(
        multiplier * int(digit)
        for multiplier, digit in enumerate(reversed(digits[:-1]), 1)
    ) % 10
    return checksum == int(digits[-1])


def finite_float(value: str) -> float | None:
    if not value:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def canonical_mol(smiles: str):
    if not smiles:
        return None, None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, None
        return mol, Chem.MolToSmiles(mol)
    except Exception:
        return None, None


def calculated_fields(smiles: str) -> tuple[str, float, float, str] | None:
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        inchikey = Chem.MolToInchiKey(mol)
        if not INCHIKEY_RE.fullmatch(inchikey):
            return None
        return (
            rdMolDescriptors.CalcMolFormula(mol),
            float(Descriptors.MolWt(mol)),
            float(Descriptors.ExactMolWt(mol)),
            inchikey,
        )
    except Exception:
        return None


def source_rows(after_row: int = 0):
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames != EXPECTED_HEADER:
            raise RuntimeError(
                f"DSSTox header mismatch: expected {EXPECTED_HEADER}, got {reader.fieldnames}"
            )
        for source_row, row in enumerate(reader, 1):
            if source_row <= after_row:
                continue
            yield source_row, row


def prepare() -> None:
    require_disk()
    source_hash = sha256_file(SOURCE)
    if source_hash != EXPECTED_SHA256:
        raise RuntimeError(
            f"DSSTox SHA256 mismatch: expected {EXPECTED_SHA256}, got {source_hash}"
        )

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pubchem'
                          AND table_name = 'chemicals'
                          AND column_name = 'name'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pubchem'
                          AND table_name = 'chemicals'
                          AND column_name = 'preferred_name'
                    ) THEN
                        ALTER TABLE pubchem.chemicals RENAME COLUMN name TO preferred_name;
                    END IF;
                END $$
                """
            )
            cur.execute(
                """
                ALTER TABLE pubchem.chemicals
                    ADD COLUMN IF NOT EXISTS dtxsid text,
                    ADD COLUMN IF NOT EXISTS iupac_name text,
                    ADD COLUMN IF NOT EXISTS molecular_formula text,
                    ADD COLUMN IF NOT EXISTS average_mass double precision,
                    ADD COLUMN IF NOT EXISTS monoisotopic_mass double precision,
                    ADD COLUMN IF NOT EXISTS inchikey text
                """
            )
            cur.execute(
                """
                COMMENT ON COLUMN pubchem.chemicals.dtxsid IS
                    'EPA DSSTox substance identifier; scalar source identity';
                COMMENT ON COLUMN pubchem.chemicals.preferred_name IS
                    'Curated preferred display name; DSSTox is the initial source';
                COMMENT ON COLUMN pubchem.chemicals.iupac_name IS
                    'Curated systematic name; DSSTox is the initial source';
                COMMENT ON COLUMN pubchem.chemicals.molecular_formula IS
                    'Materialized from canonical chemicals SMILES by RDKit';
                COMMENT ON COLUMN pubchem.chemicals.average_mass IS
                    'Average molecular mass materialized from canonical chemicals SMILES by RDKit';
                COMMENT ON COLUMN pubchem.chemicals.monoisotopic_mass IS
                    'Monoisotopic exact mass materialized from canonical chemicals SMILES by RDKit';
                COMMENT ON COLUMN pubchem.chemicals.inchikey IS
                    'Standard InChIKey materialized from canonical chemicals SMILES by RDKit'
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pubchem.dsstox_import_meta (
                    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                    source_path text NOT NULL,
                    source_sha256 text NOT NULL,
                    expected_rows bigint NOT NULL,
                    last_source_row bigint NOT NULL DEFAULT 0,
                    status text NOT NULL,
                    stats jsonb NOT NULL DEFAULT '{}'::jsonb,
                    rdkit_version text NOT NULL,
                    started_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    matched_at timestamptz,
                    completed_at timestamptz
                )
                """
            )
            cur.execute(
                """
                INSERT INTO pubchem.dsstox_import_meta
                    (source_path, source_sha256, expected_rows, status, rdkit_version)
                VALUES (%s, %s, %s, 'prepared', %s)
                ON CONFLICT (singleton) DO UPDATE SET
                    source_path = EXCLUDED.source_path,
                    source_sha256 = EXCLUDED.source_sha256,
                    expected_rows = EXCLUDED.expected_rows,
                    rdkit_version = EXCLUDED.rdkit_version,
                    updated_at = now()
                """,
                (str(SOURCE), source_hash, EXPECTED_ROWS, rdBase.rdkitVersion),
            )
            cur.execute(
                """
                CREATE UNLOGGED TABLE IF NOT EXISTS pubchem.dsstox_chemical_matches (
                    source_row bigint PRIMARY KEY,
                    pubchem_cid integer NOT NULL,
                    dtxsid text NOT NULL UNIQUE,
                    preferred_name text NOT NULL,
                    iupac_name text,
                    molecular_formula text NOT NULL,
                    average_mass double precision NOT NULL,
                    monoisotopic_mass double precision NOT NULL,
                    inchikey text NOT NULL,
                    source_casrn text NOT NULL,
                    source_dtxcid text,
                    match_method text NOT NULL,
                    imported boolean NOT NULL DEFAULT false
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS dsstox_chemical_matches_pubchem_cid_idx
                ON pubchem.dsstox_chemical_matches (pubchem_cid)
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log(f"schema prepared; source SHA256 verified; RDKit={rdBase.rdkitVersion}")


def load_state(cur) -> tuple[int, Counter]:
    cur.execute(
        """
        SELECT last_source_row, stats
        FROM pubchem.dsstox_import_meta
        WHERE singleton
        """
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("missing dsstox_import_meta; run --prepare first")
    return int(row[0]), Counter(row[1] or {})


def create_batch_table(cur) -> None:
    cur.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS dsstox_batch (
            source_row bigint PRIMARY KEY,
            dtxsid text NOT NULL,
            preferred_name text NOT NULL,
            casrn text,
            dtxcid text,
            source_inchikey text,
            iupac_name text,
            canonical_smiles text,
            source_formula text,
            source_average_mass double precision,
            source_monoisotopic_mass double precision
        ) ON COMMIT DELETE ROWS
        """
    )


def explain_candidate_plan(cur) -> None:
    cur.execute(
        """
        EXPLAIN (FORMAT TEXT)
        SELECT s.source_row, c.pubchem_cid
        FROM dsstox_batch s
        JOIN LATERAL (
            SELECT pubchem_cid
            FROM pubchem.chemicals c
            WHERE c.cas_numbers @> ARRAY[s.casrn]::text[]
              AND c.smiles IS NOT NULL
            OFFSET 0
        ) c ON true
        WHERE s.casrn IS NOT NULL AND s.canonical_smiles IS NOT NULL
        """
    )
    plan = "\n".join(row[0] for row in cur.fetchall())
    if "chemicals_identifiers_gin" not in plan:
        raise RuntimeError(f"candidate lookup is not using CAS GIN index:\n{plan}")
    log("candidate plan verified: chemicals_identifiers_gin")


def match() -> None:
    require_disk()
    conn = connect()
    try:
        with conn.cursor() as cur:
            last_row, stats = load_state(cur)
            cur.execute(
                """
                UPDATE pubchem.dsstox_import_meta
                SET status = 'matching', updated_at = now()
                WHERE singleton
                """
            )
            create_batch_table(cur)
        conn.commit()

        batch: list[tuple] = []
        batch_source: dict[int, dict] = {}
        plan_checked = False

        def process_batch(final_source_row: int) -> None:
            nonlocal plan_checked
            if not batch:
                return
            require_disk()
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO dsstox_batch
                        (source_row, dtxsid, preferred_name, casrn, dtxcid,
                         source_inchikey, iupac_name, canonical_smiles,
                         source_formula, source_average_mass,
                         source_monoisotopic_mass)
                    VALUES %s
                    """,
                    batch,
                    page_size=1000,
                )
                cur.execute("ANALYZE dsstox_batch")
                if not plan_checked:
                    explain_candidate_plan(cur)
                    plan_checked = True
                cur.execute(
                    """
                    SELECT s.source_row, c.pubchem_cid, c.smiles
                    FROM dsstox_batch s
                    JOIN LATERAL (
                        SELECT pubchem_cid, smiles
                        FROM pubchem.chemicals c
                        WHERE c.cas_numbers @> ARRAY[s.casrn]::text[]
                          AND c.smiles IS NOT NULL
                        OFFSET 0
                    ) c ON true
                    WHERE s.casrn IS NOT NULL
                      AND s.canonical_smiles IS NOT NULL
                    ORDER BY s.source_row, c.pubchem_cid
                    """
                )
                candidates: dict[int, list[tuple[int, str]]] = {}
                for source_row, pubchem_cid, smiles in cur:
                    candidates.setdefault(int(source_row), []).append(
                        (int(pubchem_cid), smiles)
                    )
                    stats["candidate_pairs"] += 1

                accepted = []
                for source_row, record in batch_source.items():
                    pairs = candidates.get(source_row, [])
                    if not pairs:
                        stats["no_pubchem_cas_candidate"] += 1
                        continue
                    strong: dict[int, tuple[str, tuple[str, float, float, str]]] = {}
                    for pubchem_cid, candidate_smiles in pairs:
                        calculated = calculated_fields(candidate_smiles)
                        if calculated is None:
                            stats["candidate_descriptor_failure"] += 1
                            continue
                        formula, avg_mass, mono_mass, candidate_key = calculated
                        methods = []
                        if candidate_smiles == record["canonical_smiles"]:
                            methods.append("canonical_smiles")
                        if (
                            record["source_inchikey"]
                            and candidate_key == record["source_inchikey"]
                        ):
                            methods.append("inchikey")
                        if methods:
                            strong[pubchem_cid] = ("+".join(methods), calculated)

                    if len(strong) != 1:
                        stats[
                            "ambiguous_strong_match" if len(strong) > 1 else "structure_mismatch"
                        ] += 1
                        continue

                    pubchem_cid, (method, calculated) = next(iter(strong.items()))
                    formula, avg_mass, mono_mass, candidate_key = calculated
                    if record["source_formula"] == formula:
                        stats["source_formula_agrees"] += 1
                    else:
                        stats["source_formula_differs"] += 1
                    source_avg = record["source_average_mass"]
                    if source_avg is not None and abs(source_avg - avg_mass) <= 0.02:
                        stats["source_average_mass_agrees"] += 1
                    elif source_avg is not None:
                        stats["source_average_mass_differs"] += 1
                    source_mono = record["source_monoisotopic_mass"]
                    if source_mono is not None and abs(source_mono - mono_mass) <= 0.00001:
                        stats["source_monoisotopic_mass_agrees"] += 1
                    elif source_mono is not None:
                        stats["source_monoisotopic_mass_differs"] += 1
                    if record["source_inchikey"] == candidate_key:
                        stats["source_inchikey_agrees"] += 1
                    else:
                        stats["source_inchikey_differs"] += 1

                    accepted.append(
                        (
                            source_row,
                            pubchem_cid,
                            record["dtxsid"],
                            record["preferred_name"],
                            record["iupac_name"],
                            formula,
                            avg_mass,
                            mono_mass,
                            candidate_key,
                            record["casrn"],
                            record["dtxcid"],
                            method,
                        )
                    )
                    stats[f"matched_by_{method}"] += 1

                if accepted:
                    execute_values(
                        cur,
                        """
                        INSERT INTO pubchem.dsstox_chemical_matches
                            (source_row, pubchem_cid, dtxsid, preferred_name,
                             iupac_name, molecular_formula, average_mass,
                             monoisotopic_mass, inchikey, source_casrn,
                             source_dtxcid, match_method)
                        VALUES %s
                        ON CONFLICT (source_row) DO NOTHING
                        """,
                        accepted,
                        page_size=1000,
                    )
                    stats["strong_matches"] += len(accepted)

                cur.execute(
                    """
                    UPDATE pubchem.dsstox_import_meta
                    SET last_source_row = %s,
                        stats = %s::jsonb,
                        updated_at = now()
                    WHERE singleton
                    """,
                    (final_source_row, json.dumps(dict(stats), sort_keys=True)),
                )
            conn.commit()

        for source_row, row in source_rows(last_row):
            stats["source_rows"] += 1
            dtxsid = (row["DTXSID"] or "").strip()
            preferred_name = (row["PREFERRED_NAME"] or "").strip()
            casrn = (row["CASRN"] or "").strip()
            smiles = (row["SMILES"] or "").strip()
            if not DTXSID_RE.fullmatch(dtxsid) or not preferred_name:
                stats["invalid_required_identity"] += 1
                canonical = None
            elif not cas_valid(casrn):
                stats["invalid_or_noncas"] += 1
                canonical = None
                casrn = ""
            elif not smiles:
                stats["no_source_structure"] += 1
                canonical = None
            else:
                _, canonical = canonical_mol(smiles)
                if canonical is None:
                    stats["source_smiles_parse_failure"] += 1

            source_key = (row["INCHIKEY"] or "").strip()
            if not INCHIKEY_RE.fullmatch(source_key):
                source_key = ""
            record = {
                "dtxsid": dtxsid,
                "preferred_name": preferred_name,
                "casrn": casrn or None,
                "dtxcid": (row["DTXCID"] or "").strip() or None,
                "source_inchikey": source_key or None,
                "iupac_name": (row["IUPAC_NAME"] or "").strip() or None,
                "canonical_smiles": canonical,
                "source_formula": (row["MOLECULAR_FORMULA"] or "").strip() or None,
                "source_average_mass": finite_float((row["AVERAGE_MASS"] or "").strip()),
                "source_monoisotopic_mass": finite_float(
                    (row["MONOISOTOPIC_MASS"] or "").strip()
                ),
            }
            batch_source[source_row] = record
            batch.append(
                (
                    source_row,
                    record["dtxsid"],
                    record["preferred_name"],
                    record["casrn"],
                    record["dtxcid"],
                    record["source_inchikey"],
                    record["iupac_name"],
                    record["canonical_smiles"],
                    record["source_formula"],
                    record["source_average_mass"],
                    record["source_monoisotopic_mass"],
                )
            )
            if len(batch) >= BATCH_ROWS:
                process_batch(source_row)
                if source_row % 50_000 == 0:
                    log(
                        f"matched source={source_row:,}/{EXPECTED_ROWS:,} "
                        f"strong={stats['strong_matches']:,} "
                        f"free={free_bytes()/1024**3:.2f}GiB"
                    )
                batch.clear()
                batch_source.clear()

        if batch:
            process_batch(max(batch_source))
            batch.clear()
            batch_source.clear()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pubchem.dsstox_chemical_matches")
            stored = int(cur.fetchone()[0])
            if stats["source_rows"] != EXPECTED_ROWS:
                raise RuntimeError(
                    f"source record mismatch: expected {EXPECTED_ROWS}, "
                    f"got {stats['source_rows']}"
                )
            if stored != stats["strong_matches"]:
                raise RuntimeError(
                    f"stored match mismatch: table={stored}, stats={stats['strong_matches']}"
                )
            cur.execute(
                """
                UPDATE pubchem.dsstox_import_meta
                SET status = 'matched', matched_at = now(), updated_at = now(),
                    stats = %s::jsonb
                WHERE singleton
                """,
                (json.dumps(dict(stats), sort_keys=True),),
            )
        conn.commit()
        log(f"matching complete: {stored:,} strong rows")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_matches() -> None:
    require_disk()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status FROM pubchem.dsstox_import_meta WHERE singleton
                """
            )
            status = cur.fetchone()[0]
            if status not in ("matched", "applying", "complete"):
                raise RuntimeError(f"matching is not complete; status={status}")
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.dsstox_chemical_matches m
                WHERE EXISTS (
                    SELECT 1 FROM pubchem.dsstox_chemical_matches x
                    WHERE x.pubchem_cid = m.pubchem_cid
                      AND x.source_row <> m.source_row
                )
                """
            )
            scalar_conflicts = int(cur.fetchone()[0])
            cur.execute(
                """
                UPDATE pubchem.dsstox_import_meta
                SET status = 'applying', updated_at = now(),
                    stats = jsonb_set(
                        stats, '{scalar_dtxsid_conflict_rows}', to_jsonb(%s::bigint), true
                    )
                WHERE singleton
                """,
                (scalar_conflicts,),
            )
        conn.commit()
        log(f"scalar DTXSID conflicts held back: {scalar_conflicts:,}")

        total = 0
        while True:
            require_disk()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH batch AS MATERIALIZED (
                        SELECT m.*
                        FROM pubchem.dsstox_chemical_matches m
                        WHERE NOT m.imported
                          AND NOT EXISTS (
                              SELECT 1
                              FROM pubchem.dsstox_chemical_matches x
                              WHERE x.pubchem_cid = m.pubchem_cid
                                AND x.source_row <> m.source_row
                          )
                        ORDER BY m.pubchem_cid
                        LIMIT %s
                        FOR UPDATE OF m SKIP LOCKED
                    ), updated AS (
                        UPDATE pubchem.chemicals c
                        SET dtxsid = b.dtxsid,
                            preferred_name = b.preferred_name,
                            iupac_name = b.iupac_name,
                            molecular_formula = b.molecular_formula,
                            average_mass = b.average_mass,
                            monoisotopic_mass = b.monoisotopic_mass,
                            inchikey = b.inchikey,
                            updated_at = now()
                        FROM batch b
                        WHERE c.pubchem_cid = b.pubchem_cid
                        RETURNING c.pubchem_cid
                    )
                    UPDATE pubchem.dsstox_chemical_matches m
                    SET imported = true
                    FROM updated u
                    WHERE m.pubchem_cid = u.pubchem_cid
                    RETURNING m.pubchem_cid
                    """,
                    (APPLY_ROWS,),
                )
                changed = len(cur.fetchall())
            conn.commit()
            if not changed:
                break
            total += changed
            log(
                f"applied={total:,}, batch={changed:,}, "
                f"free={free_bytes()/1024**3:.2f}GiB"
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE imported),
                       count(*) FILTER (WHERE NOT imported)
                FROM pubchem.dsstox_chemical_matches
                """
            )
            imported, held_back = map(int, cur.fetchone())
            cur.execute(
                """
                UPDATE pubchem.dsstox_import_meta
                SET status = 'applied', updated_at = now(),
                    stats = stats || jsonb_build_object(
                        'imported_rows', %s::bigint,
                        'held_back_rows', %s::bigint
                    )
                WHERE singleton
                """,
                (imported, held_back),
            )
        conn.commit()
        log(f"apply complete: imported={imported:,}, held_back={held_back:,}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_indexes() -> None:
    require_disk()
    statements = [
        (
            "chemicals_dtxsid_uidx",
            """
            CREATE UNIQUE INDEX chemicals_dtxsid_uidx
            ON pubchem.chemicals (dtxsid)
            WHERE dtxsid IS NOT NULL
            """,
        ),
        (
            "chemicals_inchikey_idx",
            """
            CREATE INDEX chemicals_inchikey_idx
            ON pubchem.chemicals (inchikey)
            WHERE inchikey IS NOT NULL
            """,
        ),
        (
            "chemicals_preferred_name_trgm_idx",
            """
            CREATE INDEX chemicals_preferred_name_trgm_idx
            ON pubchem.chemicals USING gin (preferred_name gin_trgm_ops)
            WHERE preferred_name IS NOT NULL
            """,
        ),
        (
            "chemicals_iupac_name_trgm_idx",
            """
            CREATE INDEX chemicals_iupac_name_trgm_idx
            ON pubchem.chemicals USING gin (iupac_name gin_trgm_ops)
            WHERE iupac_name IS NOT NULL
            """,
        ),
    ]
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SET maintenance_work_mem = '256MB'")
            for name, statement in statements:
                cur.execute("SELECT to_regclass(%s)", (f"pubchem.{name}",))
                if cur.fetchone()[0] is not None:
                    log(f"index already exists: {name}")
                    continue
                require_disk()
                started = time.monotonic()
                log(f"creating index: {name}")
                cur.execute(statement)
                log(f"index complete: {name} ({time.monotonic()-started:.1f}s)")
    finally:
        conn.close()


def verify() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, last_source_row, stats, rdkit_version
                FROM pubchem.dsstox_import_meta WHERE singleton
                """
            )
            status, last_source_row, stats, version = cur.fetchone()
            cur.execute(
                """
                SELECT count(*) AS dtxsid_rows,
                       count(*) FILTER (
                           WHERE preferred_name IS NULL
                              OR molecular_formula IS NULL
                              OR average_mass IS NULL
                              OR monoisotopic_mass IS NULL
                              OR inchikey IS NULL
                       ) AS incomplete,
                       count(DISTINCT dtxsid) AS distinct_dtxsid
                FROM pubchem.chemicals
                WHERE dtxsid IS NOT NULL
                """
            )
            loaded, incomplete, distinct_dtxsid = map(int, cur.fetchone())
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.chemicals c
                JOIN pubchem.dsstox_chemical_matches m USING (pubchem_cid)
                WHERE m.imported
                  AND (c.dtxsid, c.preferred_name, c.iupac_name,
                       c.molecular_formula, c.average_mass,
                       c.monoisotopic_mass, c.inchikey)
                      IS DISTINCT FROM
                      (m.dtxsid, m.preferred_name, m.iupac_name,
                       m.molecular_formula, m.average_mass,
                       m.monoisotopic_mass, m.inchikey)
                """
            )
            mismatches = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
                FROM pg_indexes
                WHERE schemaname = 'pubchem'
                  AND tablename = 'chemicals'
                ORDER BY indexname
                """
            )
            indexes = cur.fetchall()

            if last_source_row != EXPECTED_ROWS:
                raise RuntimeError(
                    f"source row checkpoint {last_source_row} != {EXPECTED_ROWS}"
                )
            if incomplete or loaded != distinct_dtxsid or mismatches:
                raise RuntimeError(
                    f"verification failed: loaded={loaded}, distinct={distinct_dtxsid}, "
                    f"incomplete={incomplete}, mismatches={mismatches}"
                )
            cur.execute(
                """
                UPDATE pubchem.dsstox_import_meta
                SET status = 'complete', completed_at = now(), updated_at = now()
                WHERE singleton
                """
            )
            cur.execute("DROP TABLE pubchem.dsstox_chemical_matches")
        conn.commit()
        print(
            json.dumps(
                {
                    "status_before_verify": status,
                    "loaded_rows": loaded,
                    "incomplete_rows": incomplete,
                    "distinct_dtxsid": distinct_dtxsid,
                    "data_mismatches": mismatches,
                    "rdkit_version": version,
                    "stats": stats,
                    "indexes": indexes,
                    "disk_free_gib": round(free_bytes() / 1024**3, 3),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def vacuum_analyze() -> None:
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            log("VACUUM (ANALYZE) pubchem.chemicals")
            cur.execute("VACUUM (ANALYZE) pubchem.chemicals")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("prepare", "match", "apply", "indexes", "verify", "vacuum", "all"),
    )
    args = parser.parse_args()
    if args.action in ("prepare", "all"):
        prepare()
    if args.action in ("match", "all"):
        match()
    if args.action in ("apply", "all"):
        apply_matches()
    if args.action in ("indexes", "all"):
        create_indexes()
    if args.action in ("vacuum", "all"):
        vacuum_analyze()
    if args.action in ("verify", "all"):
        verify()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted safely; rerun the same action to resume")
        raise SystemExit(130)
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise
