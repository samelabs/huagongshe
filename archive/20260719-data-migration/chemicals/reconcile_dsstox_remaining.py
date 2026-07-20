#!/usr/bin/env python3
"""Progressively reconcile residual DSSTox records with existing chemicals.

This second pass does not create chemicals.  It first materializes only DTXSIDs
not already attached, then performs a single hash join over chemicals.smiles.
Only bidirectionally unique exact-structure matches are eligible for update.
All other rows remain staged for later salt/charge/stereo/CAS classification.
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
import time
from collections import Counter
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import Descriptors, rdMolDescriptors


SOURCE = Path("/var/www/ord-samelabs/DSSToxCCDdump.csv")
EXPECTED_SHA256 = "e69f56b35ce9d626810c6df2b5c79c48d0c3bb50ccde399da30687c6dd6d6a1b"
EXPECTED_SOURCE_ROWS = 1_246_399
EXPECTED_INITIAL_RESIDUAL = 174_009
DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
BATCH_ROWS = int(os.environ.get("DSSTOX_RECONCILE_BATCH_ROWS", "5000"))
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
        cur.execute("SET application_name='dsstox_residual_reconcile'")
        cur.execute("SET statement_timeout=0")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET wal_compression=on")
        cur.execute("SET synchronous_commit=off")
    if not autocommit:
        conn.commit()
    return conn


def free_bytes() -> int:
    return shutil.disk_usage("/").free


def require_disk() -> None:
    available = free_bytes()
    if available < MIN_FREE_BYTES:
        raise RuntimeError(
            f"disk guard: {available/1024**3:.2f}GiB free, "
            f"minimum={MIN_FREE_BYTES/1024**3:.2f}GiB"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cas_valid(value: str) -> bool:
    if not CAS_RE.fullmatch(value):
        return False
    digits = value.replace("-", "")
    checksum = sum(
        multiplier * int(digit)
        for multiplier, digit in enumerate(reversed(digits[:-1]), 1)
    ) % 10
    return checksum == int(digits[-1])


def source_records():
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        expected = [
            "DTXSID", "PREFERRED_NAME", "CASRN", "DTXCID", "INCHIKEY",
            "IUPAC_NAME", "SMILES", "MOLECULAR_FORMULA", "AVERAGE_MASS",
            "MONOISOTOPIC_MASS", "QSAR_READY_SMILES", "MS_READY_SMILES",
            "IDENTIFIER",
        ]
        if reader.fieldnames != expected:
            raise RuntimeError(f"DSSTox header mismatch: {reader.fieldnames}")
        yield from enumerate(reader, 1)


def normalize_structure(smiles: str):
    if not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        canonical = Chem.MolToSmiles(mol)
        inchikey = Chem.MolToInchiKey(mol)
        return (
            canonical,
            inchikey if INCHIKEY_RE.fullmatch(inchikey) else None,
            inchikey[:14] if INCHIKEY_RE.fullmatch(inchikey) else None,
            rdMolDescriptors.CalcMolFormula(mol),
            float(Descriptors.MolWt(mol)),
            float(Descriptors.ExactMolWt(mol)),
        )
    except Exception:
        return None


def finite_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def prepare_residual() -> None:
    require_disk()
    source_hash = sha256_file(SOURCE)
    if source_hash != EXPECTED_SHA256:
        raise RuntimeError(
            f"source SHA256 mismatch: expected {EXPECTED_SHA256}, got {source_hash}"
        )
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DROP TABLE IF EXISTS pubchem.dsstox_residual_exact_safe;
                DROP TABLE IF EXISTS pubchem.dsstox_residual_exact_candidates;
                DROP TABLE IF EXISTS pubchem.dsstox_residual_stage;
                CREATE UNLOGGED TABLE pubchem.dsstox_residual_stage (
                    source_row integer PRIMARY KEY,
                    dtxsid text NOT NULL UNIQUE,
                    preferred_name text NOT NULL,
                    casrn text,
                    cas_is_valid boolean NOT NULL,
                    dtxcid text,
                    source_inchikey text,
                    iupac_name text,
                    source_smiles text,
                    canonical_smiles text,
                    calculated_inchikey text,
                    connectivity_key text,
                    calculated_formula text,
                    calculated_average_mass double precision,
                    calculated_monoisotopic_mass double precision,
                    source_formula text,
                    source_average_mass double precision,
                    source_monoisotopic_mass double precision
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pubchem.dsstox_reconcile_meta (
                    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                    source_sha256 text NOT NULL,
                    source_rows bigint NOT NULL,
                    initial_residual_rows bigint NOT NULL,
                    stats jsonb NOT NULL DEFAULT '{}'::jsonb,
                    status text NOT NULL,
                    rdkit_version text NOT NULL,
                    started_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    completed_at timestamptz
                )
                """
            )
            cur.execute(
                """
                INSERT INTO pubchem.dsstox_reconcile_meta
                    (source_sha256, source_rows, initial_residual_rows,
                     status, rdkit_version)
                VALUES (%s,%s,0,'staging',%s)
                ON CONFLICT (singleton) DO UPDATE SET
                    source_sha256=EXCLUDED.source_sha256,
                    source_rows=EXCLUDED.source_rows,
                    initial_residual_rows=0,
                    stats='{}'::jsonb,
                    status='staging',
                    rdkit_version=EXCLUDED.rdkit_version,
                    started_at=now(), updated_at=now(), completed_at=NULL
                """,
                (source_hash, EXPECTED_SOURCE_ROWS, rdBase.rdkitVersion),
            )
        conn.commit()

        stats = Counter()
        batch = []

        def flush() -> None:
            if not batch:
                return
            require_disk()
            dtxsids = [row[1]["DTXSID"].strip() for row in batch]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT dtxsid FROM pubchem.chemicals
                    WHERE dtxsid = ANY(%s)
                    """,
                    (dtxsids,),
                )
                existing = {row[0] for row in cur.fetchall()}
                values = []
                for source_row, row in batch:
                    dtxsid = row["DTXSID"].strip()
                    if dtxsid in existing:
                        stats["already_attached"] += 1
                        continue
                    if not DTXSID_RE.fullmatch(dtxsid):
                        raise RuntimeError(f"invalid DTXSID at source row {source_row}")
                    preferred_name = row["PREFERRED_NAME"].strip()
                    if not preferred_name:
                        raise RuntimeError(f"empty preferred name at row {source_row}")
                    casrn = row["CASRN"].strip()
                    valid_cas = cas_valid(casrn)
                    source_smiles = row["SMILES"].strip() or None
                    normalized = normalize_structure(source_smiles or "")
                    if normalized is None:
                        canonical = calculated_key = connectivity = formula = None
                        average = mono = None
                        stats[
                            "no_source_smiles" if source_smiles is None
                            else "source_smiles_parse_failure"
                        ] += 1
                    else:
                        canonical, calculated_key, connectivity, formula, average, mono = normalized
                        stats["structured"] += 1
                    if valid_cas:
                        stats["valid_cas"] += 1
                    else:
                        stats["invalid_or_noncas"] += 1
                    source_key = row["INCHIKEY"].strip() or None
                    if source_key and not INCHIKEY_RE.fullmatch(source_key):
                        source_key = None
                    values.append(
                        (
                            source_row, dtxsid, preferred_name,
                            casrn if valid_cas else None, valid_cas,
                            row["DTXCID"].strip() or None, source_key,
                            row["IUPAC_NAME"].strip() or None, source_smiles,
                            canonical, calculated_key, connectivity, formula,
                            average, mono,
                            row["MOLECULAR_FORMULA"].strip() or None,
                            finite_float(row["AVERAGE_MASS"].strip()),
                            finite_float(row["MONOISOTOPIC_MASS"].strip()),
                        )
                    )
                if values:
                    execute_values(
                        cur,
                        """
                        INSERT INTO pubchem.dsstox_residual_stage
                            (source_row,dtxsid,preferred_name,casrn,cas_is_valid,
                             dtxcid,source_inchikey,iupac_name,source_smiles,
                             canonical_smiles,calculated_inchikey,connectivity_key,
                             calculated_formula,calculated_average_mass,
                             calculated_monoisotopic_mass,source_formula,
                             source_average_mass,source_monoisotopic_mass)
                        VALUES %s
                        """,
                        values,
                        page_size=len(values),
                    )
                    stats["residual_rows"] += len(values)
            conn.commit()

        last_row = 0
        for source_row, row in source_records():
            last_row = source_row
            batch.append((source_row, row))
            if len(batch) >= BATCH_ROWS:
                flush()
                if source_row % 100_000 == 0:
                    log(
                        f"staged source={source_row:,}, "
                        f"residual={stats['residual_rows']:,}, "
                        f"free={free_bytes()/1024**3:.2f}GiB"
                    )
                batch.clear()
        flush()

        if last_row != EXPECTED_SOURCE_ROWS:
            raise RuntimeError(
                f"source rows {last_row} != expected {EXPECTED_SOURCE_ROWS}"
            )
        if stats["residual_rows"] != EXPECTED_INITIAL_RESIDUAL:
            raise RuntimeError(
                f"residual rows {stats['residual_rows']} != "
                f"expected {EXPECTED_INITIAL_RESIDUAL}"
            )
        if stats["already_attached"] + stats["residual_rows"] != EXPECTED_SOURCE_ROWS:
            raise RuntimeError("attached + residual does not equal source total")
        with conn.cursor() as cur:
            cur.execute("ANALYZE pubchem.dsstox_residual_stage")
            cur.execute(
                """
                UPDATE pubchem.dsstox_reconcile_meta
                SET initial_residual_rows=%s, stats=%s::jsonb,
                    status='staged', updated_at=now()
                WHERE singleton
                """,
                (stats["residual_rows"], json.dumps(dict(stats), sort_keys=True)),
            )
        conn.commit()
        log(f"residual staging complete: {stats['residual_rows']:,} rows")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def global_exact() -> None:
    require_disk()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET work_mem='256MB'")
            cur.execute("SET enable_nestloop=off")
            cur.execute("SET enable_mergejoin=off")
            cur.execute(
                """
                EXPLAIN (FORMAT TEXT)
                SELECT r.source_row,c.pubchem_cid
                FROM pubchem.chemicals c
                JOIN pubchem.dsstox_residual_stage r
                  ON r.canonical_smiles=c.smiles
                WHERE r.canonical_smiles IS NOT NULL
                """
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
            if "Hash Join" not in plan or "Seq Scan on chemicals" not in plan:
                raise RuntimeError(f"unsafe global exact plan:\n{plan}")
            log("global exact plan verified: one chemicals scan + residual hash")
            cur.execute("DROP TABLE IF EXISTS pubchem.dsstox_residual_exact_safe")
            cur.execute("DROP TABLE IF EXISTS pubchem.dsstox_residual_exact_candidates")
            started = time.monotonic()
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.dsstox_residual_exact_candidates AS
                SELECT r.source_row,r.dtxsid,c.pubchem_cid,c.dtxsid AS target_dtxsid
                FROM pubchem.chemicals c
                JOIN pubchem.dsstox_residual_stage r
                  ON r.canonical_smiles=c.smiles
                WHERE r.canonical_smiles IS NOT NULL
                """
            )
            candidate_pairs = cur.rowcount
            log(
                f"global exact scan complete: pairs={candidate_pairs:,}, "
                f"elapsed={time.monotonic()-started:.1f}s"
            )
            cur.execute(
                """
                CREATE INDEX dsstox_residual_exact_source_idx
                ON pubchem.dsstox_residual_exact_candidates(source_row);
                CREATE INDEX dsstox_residual_exact_cid_idx
                ON pubchem.dsstox_residual_exact_candidates(pubchem_cid);
                ANALYZE pubchem.dsstox_residual_exact_candidates
                """
            )
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.dsstox_residual_exact_safe AS
                WITH source_unique AS (
                    SELECT source_row,min(pubchem_cid) AS pubchem_cid
                    FROM pubchem.dsstox_residual_exact_candidates
                    GROUP BY source_row
                    HAVING count(*)=1 AND count(*) FILTER (WHERE target_dtxsid IS NULL)=1
                ), target_unique AS (
                    SELECT pubchem_cid,min(source_row) AS source_row
                    FROM pubchem.dsstox_residual_exact_candidates
                    WHERE target_dtxsid IS NULL
                    GROUP BY pubchem_cid
                    HAVING count(*)=1
                )
                SELECT s.source_row,s.pubchem_cid
                FROM source_unique s
                JOIN target_unique t USING (source_row,pubchem_cid)
                """
            )
            safe_rows = cur.rowcount
            cur.execute(
                """
                ALTER TABLE pubchem.dsstox_residual_exact_safe
                    ADD PRIMARY KEY(source_row),
                    ADD UNIQUE(pubchem_cid)
                """
            )
            cur.execute(
                """
                SELECT
                    count(DISTINCT source_row) AS matched_residual,
                    count(*) FILTER (WHERE target_dtxsid IS NOT NULL) AS occupied_pairs,
                    count(*) AS pairs
                FROM pubchem.dsstox_residual_exact_candidates
                """
            )
            matched_residual, occupied_pairs, pairs = map(int, cur.fetchone())
            stats = {
                "exact_candidate_pairs": pairs,
                "exact_matched_residual_rows": matched_residual,
                "exact_occupied_target_pairs": occupied_pairs,
                "exact_safe_rows": safe_rows,
            }
            cur.execute(
                """
                UPDATE pubchem.dsstox_reconcile_meta
                SET stats=stats || %s::jsonb,status='exact_classified',updated_at=now()
                WHERE singleton
                """,
                (json.dumps(stats, sort_keys=True),),
            )
        conn.commit()
        log(json.dumps(stats, sort_keys=True))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_exact() -> None:
    require_disk()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status,stats->>'exact_safe_rows'
                FROM pubchem.dsstox_reconcile_meta WHERE singleton
                """
            )
            status, expected = cur.fetchone()
            if status not in ("exact_classified", "exact_applied"):
                raise RuntimeError(f"exact classification is not ready; status={status}")
            expected = int(expected)
            cur.execute(
                """
                WITH updated AS (
                    UPDATE pubchem.chemicals c
                    SET dtxsid=r.dtxsid,
                        preferred_name=r.preferred_name,
                        iupac_name=r.iupac_name,
                        molecular_formula=r.calculated_formula,
                        average_mass=r.calculated_average_mass,
                        monoisotopic_mass=r.calculated_monoisotopic_mass,
                        inchikey=r.calculated_inchikey,
                        cas_numbers=CASE
                            WHEN r.cas_is_valid AND NOT (
                                r.casrn=ANY(coalesce(c.cas_numbers,ARRAY[]::text[]))
                            ) THEN array_prepend(r.casrn,coalesce(c.cas_numbers,ARRAY[]::text[]))
                            ELSE c.cas_numbers
                        END,
                        updated_at=now()
                    FROM pubchem.dsstox_residual_exact_safe s
                    JOIN pubchem.dsstox_residual_stage r USING(source_row)
                    WHERE c.pubchem_cid=s.pubchem_cid
                      AND c.dtxsid IS NULL
                    RETURNING c.pubchem_cid,c.dtxsid
                )
                SELECT count(*),count(DISTINCT dtxsid) FROM updated
                """
            )
            updated, distinct_dtxsid = map(int, cur.fetchone())
            if updated != expected or distinct_dtxsid != expected:
                raise RuntimeError(
                    f"exact update mismatch: expected={expected}, updated={updated}, "
                    f"distinct={distinct_dtxsid}"
                )
            cur.execute(
                """
                SELECT count(*)
                FROM pubchem.dsstox_residual_exact_safe s
                JOIN pubchem.dsstox_residual_stage r USING(source_row)
                JOIN pubchem.chemicals c USING(pubchem_cid)
                WHERE (c.dtxsid,c.preferred_name,c.iupac_name,c.molecular_formula,
                       c.average_mass,c.monoisotopic_mass,c.inchikey)
                      IS DISTINCT FROM
                      (r.dtxsid,r.preferred_name,r.iupac_name,r.calculated_formula,
                       r.calculated_average_mass,r.calculated_monoisotopic_mass,
                       r.calculated_inchikey)
                """
            )
            mismatches = int(cur.fetchone()[0])
            if mismatches:
                raise RuntimeError(f"post-update exact mismatches={mismatches}")
            cur.execute(
                """
                UPDATE pubchem.dsstox_reconcile_meta
                SET stats=stats || jsonb_build_object(
                        'exact_applied_rows',%s::bigint,
                        'exact_post_update_mismatches',%s::bigint
                    ),status='exact_applied',updated_at=now()
                WHERE singleton
                """,
                (updated, mismatches),
            )
        conn.commit()
        log(f"exact apply complete: {updated:,} rows")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def report() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status,stats,rdkit_version,updated_at
                FROM pubchem.dsstox_reconcile_meta WHERE singleton
                """
            )
            status, stats, version, updated_at = cur.fetchone()
            cur.execute(
                """
                SELECT
                    count(*) AS residual_stage,
                    count(*) FILTER (WHERE canonical_smiles IS NOT NULL) AS structured,
                    count(*) FILTER (WHERE canonical_smiles IS NULL) AS unstructured,
                    count(*) FILTER (WHERE cas_is_valid) AS valid_cas
                FROM pubchem.dsstox_residual_stage
                """
            )
            residual_stage, structured, unstructured, valid_cas = map(int, cur.fetchone())
            cur.execute(
                """
                SELECT
                    count(*) FILTER (WHERE c.dtxsid IS NOT NULL) AS now_attached,
                    count(*) FILTER (WHERE c.dtxsid IS NULL) AS still_unattached
                FROM pubchem.dsstox_residual_stage r
                LEFT JOIN pubchem.chemicals c ON c.dtxsid=r.dtxsid
                """
            )
            now_attached, still_unattached = map(int, cur.fetchone())
            output = {
                "status": status,
                "stats": stats,
                "rdkit_version": version,
                "updated_at": str(updated_at),
                "residual_stage": residual_stage,
                "structured": structured,
                "unstructured": unstructured,
                "valid_cas": valid_cas,
                "now_attached": now_attached,
                "still_unattached": still_unattached,
                "disk_free_gib": round(free_bytes()/1024**3, 3),
            }
            print(json.dumps(output,ensure_ascii=False,indent=2,default=str))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action",choices=("prepare","global-exact","apply-exact","report"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare_residual()
    elif args.action == "global-exact":
        global_exact()
    elif args.action == "apply-exact":
        apply_exact()
    else:
        report()


if __name__ == "__main__":
    main()
