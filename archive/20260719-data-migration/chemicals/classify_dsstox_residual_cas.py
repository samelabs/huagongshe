#!/usr/bin/env python3
"""Classify CAS-linked residual DSSTox candidates without changing chemicals."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from functools import lru_cache

import psycopg2
from psycopg2.extras import execute_values
from rdkit import Chem, RDLogger


DB_DSN = os.environ.get(
    "PUBCHEM_DATABASE_URL",
    "dbname=huagongshe user=huagongshe host=127.0.0.1",
)
MIN_FREE_BYTES = int(os.environ.get("DSSTOX_MIN_FREE_BYTES", str(5 * 1024**3)))
RDLogger.DisableLog("rdApp.*")


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def free_bytes() -> int:
    return shutil.disk_usage("/").free


def require_disk() -> None:
    if free_bytes() < MIN_FREE_BYTES:
        raise RuntimeError(
            f"disk guard: {free_bytes()/1024**3:.2f}GiB free, "
            f"minimum={MIN_FREE_BYTES/1024**3:.2f}GiB"
        )


def connect():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET application_name='dsstox_residual_cas_classify'")
        cur.execute("SET statement_timeout=0")
        cur.execute("SET lock_timeout='30s'")
        cur.execute("SET synchronous_commit=off")
    conn.commit()
    return conn


@lru_cache(maxsize=250_000)
def profile(smiles: str | None):
    if not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        canonical = Chem.MolToSmiles(mol)
        key = Chem.MolToInchiKey(mol)
        return (
            canonical,
            key,
            key[:14],
        )
    except Exception:
        return None


def prepare_and_classify() -> None:
    require_disk()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS pubchem.dsstox_residual_cas_classification")
            cur.execute(
                """
                CREATE UNLOGGED TABLE pubchem.dsstox_residual_cas_classification (
                    source_row integer NOT NULL,
                    pubchem_cid integer NOT NULL,
                    target_dtxsid text,
                    source_kind text NOT NULL,
                    candidate_has_structure boolean NOT NULL,
                    exact_smiles boolean NOT NULL,
                    full_inchikey boolean NOT NULL,
                    same_connectivity boolean NOT NULL,
                    same_fragment_parent boolean,
                    same_charge_parent boolean,
                    same_tautomer_parent boolean,
                    PRIMARY KEY(source_row,pubchem_cid)
                )
                """
            )
            cur.execute(
                """
                EXPLAIN (FORMAT TEXT)
                SELECT r.source_row,c.pubchem_cid
                FROM pubchem.dsstox_residual_stage r
                JOIN LATERAL (
                    SELECT pubchem_cid
                    FROM pubchem.chemicals c
                    WHERE c.cas_numbers @> ARRAY[r.casrn]::text[]
                    OFFSET 0
                ) c ON true
                WHERE r.cas_is_valid
                  AND NOT EXISTS (
                      SELECT 1 FROM pubchem.chemicals x WHERE x.dtxsid=r.dtxsid
                  )
                """
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
            if "chemicals_identifiers_gin" not in plan:
                raise RuntimeError(f"CAS candidate plan does not use GIN:\n{plan}")
            log("CAS candidate plan verified: chemicals_identifiers_gin")
            cur.execute(
                """
                SELECT r.source_row,r.source_smiles,r.canonical_smiles,
                       c.pubchem_cid,c.smiles,c.dtxsid
                FROM pubchem.dsstox_residual_stage r
                JOIN LATERAL (
                    SELECT pubchem_cid,smiles,dtxsid
                    FROM pubchem.chemicals c
                    WHERE c.cas_numbers @> ARRAY[r.casrn]::text[]
                    OFFSET 0
                ) c ON true
                WHERE r.cas_is_valid
                  AND NOT EXISTS (
                      SELECT 1 FROM pubchem.chemicals x WHERE x.dtxsid=r.dtxsid
                  )
                ORDER BY r.source_row,c.pubchem_cid
                """
            )
            pairs = cur.fetchall()
        log(f"CAS candidate pairs fetched: {len(pairs):,}")

        values = []
        stats = {
            "candidate_pairs": len(pairs),
            "candidate_parse_failures": 0,
        }
        for source_row, source_smiles, canonical_smiles, cid, target_smiles, target_dtxsid in pairs:
            source_kind = (
                "no_source_smiles" if source_smiles is None
                else "structured" if canonical_smiles is not None
                else "source_parse_failure"
            )
            source_profile = profile(source_smiles) if canonical_smiles is not None else None
            target_profile = profile(target_smiles) if source_profile is not None else None
            if target_smiles and target_profile is None:
                stats["candidate_parse_failures"] += 1
            comparable = source_profile is not None and target_profile is not None
            values.append(
                (
                    source_row,
                    cid,
                    target_dtxsid,
                    source_kind,
                    target_profile is not None,
                    comparable and source_profile[0] == target_profile[0],
                    comparable and source_profile[1] == target_profile[1],
                    comparable and source_profile[2] == target_profile[2],
                    None,
                    None,
                    None,
                )
            )
            if len(values) >= 5000:
                require_disk()
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        """
                        INSERT INTO pubchem.dsstox_residual_cas_classification
                            (source_row,pubchem_cid,target_dtxsid,source_kind,
                             candidate_has_structure,exact_smiles,full_inchikey,
                             same_connectivity,same_fragment_parent,
                             same_charge_parent,same_tautomer_parent)
                        VALUES %s
                        """,
                        values,
                        page_size=len(values),
                    )
                conn.commit()
                values.clear()
        if values:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO pubchem.dsstox_residual_cas_classification
                        (source_row,pubchem_cid,target_dtxsid,source_kind,
                         candidate_has_structure,exact_smiles,full_inchikey,
                         same_connectivity,same_fragment_parent,
                         same_charge_parent,same_tautomer_parent)
                    VALUES %s
                    """,
                    values,
                    page_size=len(values),
                )
            conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE INDEX dsstox_residual_cas_cid_idx
                ON pubchem.dsstox_residual_cas_classification(pubchem_cid);
                ANALYZE pubchem.dsstox_residual_cas_classification
                """
            )
            conditions = {
                "exact_smiles": "exact_smiles",
                "full_inchikey": "full_inchikey",
                "same_connectivity": "same_connectivity",
                "cas_only_no_source_smiles": "source_kind='no_source_smiles'",
                "cas_only_source_parse_failure": "source_kind='source_parse_failure'",
            }
            for label, condition in conditions.items():
                cur.execute(
                    f"""
                    WITH source_unique AS (
                        SELECT source_row,min(pubchem_cid) AS pubchem_cid
                        FROM pubchem.dsstox_residual_cas_classification
                        WHERE ({condition}) AND target_dtxsid IS NULL
                        GROUP BY source_row HAVING count(*)=1
                    ), target_unique AS (
                        SELECT pubchem_cid,min(source_row) AS source_row
                        FROM pubchem.dsstox_residual_cas_classification
                        WHERE ({condition}) AND target_dtxsid IS NULL
                        GROUP BY pubchem_cid HAVING count(*)=1
                    )
                    SELECT count(*)
                    FROM source_unique s JOIN target_unique t USING(source_row,pubchem_cid)
                    """
                )
                stats[f"bidirectional_unique_{label}"] = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT source_kind,count(DISTINCT source_row),count(*)
                FROM pubchem.dsstox_residual_cas_classification
                GROUP BY source_kind ORDER BY source_kind
                """
            )
            stats["by_source_kind"] = {
                kind: {"sources": int(sources), "pairs": int(count)}
                for kind, sources, count in cur.fetchall()
            }
            cur.execute(
                """
                SELECT
                    count(DISTINCT source_row),
                    count(DISTINCT source_row) FILTER (WHERE target_dtxsid IS NOT NULL),
                    count(*) FILTER (WHERE exact_smiles),
                    count(*) FILTER (WHERE full_inchikey),
                    count(*) FILTER (WHERE same_connectivity),
                    count(*) FILTER (WHERE same_fragment_parent IS TRUE),
                    count(*) FILTER (WHERE same_charge_parent IS TRUE),
                    count(*) FILTER (WHERE same_tautomer_parent IS TRUE)
                FROM pubchem.dsstox_residual_cas_classification
                """
            )
            (
                sources_with_candidate,
                sources_with_occupied,
                exact_pairs,
                full_pairs,
                connectivity_pairs,
                fragment_pairs,
                charge_pairs,
                tautomer_pairs,
            ) = map(int, cur.fetchone())
            stats.update(
                {
                    "sources_with_cas_candidate": sources_with_candidate,
                    "sources_with_occupied_target": sources_with_occupied,
                    "exact_pairs": exact_pairs,
                    "full_inchikey_pairs": full_pairs,
                    "connectivity_pairs": connectivity_pairs,
                    "fragment_parent_pairs": fragment_pairs,
                    "charge_parent_pairs": charge_pairs,
                    "tautomer_parent_pairs": tautomer_pairs,
                }
            )
            cur.execute(
                """
                UPDATE pubchem.dsstox_reconcile_meta
                SET stats=stats || %s::jsonb,status='cas_classified',updated_at=now()
                WHERE singleton
                """,
                (json.dumps(stats, sort_keys=True),),
            )
        conn.commit()
        print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def samples() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.dtxsid,r.casrn,left(r.preferred_name,80),
                       x.pubchem_cid,x.source_kind,x.exact_smiles,x.full_inchikey,
                       x.same_connectivity,x.same_fragment_parent,
                       x.same_charge_parent,x.same_tautomer_parent,
                       left(r.canonical_smiles,80),left(c.smiles,80),x.target_dtxsid
                FROM pubchem.dsstox_residual_cas_classification x
                JOIN pubchem.dsstox_residual_stage r USING(source_row)
                JOIN pubchem.chemicals c USING(pubchem_cid)
                WHERE NOT x.exact_smiles
                  AND x.same_connectivity
                ORDER BY x.source_row,x.pubchem_cid
                LIMIT 30
                """
            )
            for row in cur.fetchall():
                print("\t".join("" if value is None else str(value) for value in row))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("classify", "samples"))
    args = parser.parse_args()
    if args.action == "classify":
        prepare_and_classify()
    else:
        samples()


if __name__ == "__main__":
    main()
