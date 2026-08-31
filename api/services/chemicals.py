"""化合物查询/拼装服务层 — 自 api/routes.py 下沉, 逻辑零改动(批次3c)。

外部引用者: routes(13端点), tests/test_search.py。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from rdkit import Chem
from sqlalchemy import text

from ..chemistry import normalize_doi

def clean_float(value: Any, round_digits: int | None = None) -> float | None:
    """Convert to float, mapping NaN/Infinity to None.

    Postgres float8 columns can hold NaN (e.g. ord.temperature.value).
    FastAPI's JSONResponse uses allow_nan=False, so a NaN reaching the
    serializer raises ValueError → HTTP 500.  This function sanitizes
    database values before they enter the response dict.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / ±Inf
        return None
    return round(f, round_digits) if round_digits is not None else f

IDENTIFIER_ARRAYS = {
    "cas": "cas_numbers",
    "nikkaji": "nikkaji_numbers",
    "chembl": "chembl_ids",
    "ec": "ec_numbers",
    "unii": "unii_codes",
    "chebi": "chebi_ids",
}
FULL_DETAILS_SECTIONS = (
    "computed", "identifiers", "synonyms", "physical", "safety",
    "toxicity", "regulatory", "pharmacology", "uses",
)
CHEMICAL_SELECT = """
    c.id, c.pubchem_cid, c.smiles, c.pubchem_smiles,
    c.preferred_name, c.iupac_name, c.molecular_formula,
    c.average_mass, c.monoisotopic_mass, c.inchikey, c.dtxsid,
    c.cas_numbers, c.nikkaji_numbers, c.chembl_ids, c.ec_numbers,
    c.unii_codes, c.chebi_ids
"""
# Smaller motifs match too much of the 124M-compound corpus and can remain inside
# RDKit's PostgreSQL extension after the client-side statement timeout expires.
MIN_SUBSTRUCTURE_HEAVY_ATOMS = 10
# 名称最短长度按"宽度单位"计: CJK 字符(中日韩)每个算 2 单位, 其余 1 单位。
# 拉丁 1-2 字符对 124M 行的 ILIKE 模糊扫描过宽, 3 单位起查; 中文 2 字完整词
# (乙醇=4 单位)选择性极高, 不再误拦; 单字"醇"(2 单位)仍拦。
# 例外：完整 CAS 号/标识符走精确分支，不受此限。
MIN_FUZZY_NAME_LENGTH = 3


def name_query_width(query: str) -> int:
    """名称查询宽度: CJK 计 2, 其余计 1。用于最短长度判定。"""
    return sum(2 if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff'
               or '\uac00' <= ch <= '\ud7af' else 1 for ch in query)


def bounded_substructure_smiles(smiles: str) -> str:
    """Reject queries whose result set is effectively unbounded at PubChem scale."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(400, "无法识别该 SMILES 结构")
    if mol.GetNumHeavyAtoms() < MIN_SUBSTRUCTURE_HEAVY_ATOMS:
        raise HTTPException(422, f"子结构过小，请至少提供 {MIN_SUBSTRUCTURE_HEAVY_ATOMS} 个非氢原子")
    return smiles


def chemical_dict(row: Any, score: float | None = None) -> dict[str, Any]:
    return {
        "id": row[0],
        "pubchem_cid": row[1],
        "smiles": row[2],
        "pubchem_smiles": row[3],
        "preferred_name": row[4],
        "iupac_name": row[5],
        "molecular_formula": row[6],
        "average_mass": clean_float(row[7]),
        "monoisotopic_mass": clean_float(row[8]),
        "inchikey": row[9],
        "dtxsid": row[10],
        "cas_numbers": row[11] or [],
        "nikkaji_numbers": row[12] or [],
        "chembl_ids": row[13] or [],
        "ec_numbers": row[14] or [],
        "unii_codes": row[15] or [],
        "chebi_ids": row[16] or [],
        "similarity": clean_float(score, round_digits=4),
    }


async def fetch_chemicals(db: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (await db.execute(text(sql), params)).fetchall()
    return [chemical_dict(row, row[17] if len(row) > 17 else None) for row in rows]


async def reaction_summaries(
    db: Any,
    chemical_ids: list[int],
    role: str,
    page: int,
    page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    if not chemical_ids:
        return 0, []
    role_clause = ""
    params: dict[str, Any] = {"chemical_ids": chemical_ids}
    if role != "any":
        role_clause = "AND rc.role = :role"
        params["role"] = role.upper()
    total_all = int((await db.execute(text(f"""
        SELECT count(DISTINCT rc.reaction_id)
        FROM chemistry.reaction_chemicals rc
        WHERE rc.chemical_id = ANY(:chemical_ids) {role_clause}
    """), params)).scalar() or 0)
    excluded = int((await db.execute(text(f"""
        SELECT count(DISTINCT rc.reaction_id)
        FROM chemistry.reactions rx
        JOIN chemistry.reaction_chemicals rc ON rc.reaction_id=rx.id
        WHERE (rx.visibility<>'public' OR rx.moderation_status<>'visible')
          AND rc.chemical_id = ANY(:chemical_ids) {role_clause}
    """), params)).scalar() or 0)
    total = max(total_all - excluded, 0)
    params.update(limit=page_size, offset=(page - 1) * page_size)
    rows = (await db.execute(text(f"""
        WITH ids AS MATERIALIZED (
            SELECT DISTINCT rc.reaction_id
            FROM chemistry.reaction_chemicals rc
            WHERE rc.chemical_id = ANY(:chemical_ids) {role_clause}
              AND NOT EXISTS (
                SELECT 1 FROM chemistry.reactions excluded_rx
                WHERE excluded_rx.id=rc.reaction_id
                  AND (excluded_rx.visibility<>'public' OR excluded_rx.moderation_status<>'visible')
              )
            ORDER BY rc.reaction_id
            LIMIT :limit OFFSET :offset
        )
        SELECT DISTINCT ON (rx.id)
            rx.id, rx.reaction_smiles,
            COALESCE(NULLIF(rx.doi,''),rp.doi),
            COALESCE(NULLIF(rx.patent,''),rp.patent),
            CASE WHEN rx.created_by_user_id IS NOT NULL
                 THEN COALESCE(NULLIF(rx.source_citation,''),'用户发布') ELSE d.name END,
            (SELECT array_agg(DISTINCT rc.role ORDER BY rc.role)
             FROM chemistry.reaction_chemicals rc
             WHERE rc.reaction_id=rx.id AND rc.chemical_id=ANY(:chemical_ids))
        FROM ids
        JOIN chemistry.reactions rx ON rx.id = ids.reaction_id
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id = rx.id
        LEFT JOIN ord.reaction o ON o.id = lm.ord_reaction_id
        LEFT JOIN ord.reaction_provenance rp ON rp.reaction_id = o.id
        LEFT JOIN ord.dataset d ON d.id = o.dataset_id
        ORDER BY rx.id, rp.id
    """), params)).fetchall()
    return total, [
        {
            "id": row[0], "reaction_smiles": row[1], "doi": row[2],
            "patent": row[3], "dataset_name": row[4],
            "matched_roles": row[5] or [],
        }
        for row in rows
    ]


async def reaction_lookup(db: Any, query: str, limit: int) -> list[dict[str, Any]]:
    """Resolve stable reaction identities; chemical structures are searched as chemicals."""
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": min(limit, 100)}
    prefix, sep, raw_value = query.partition(":")
    value = raw_value.strip() if sep else query
    normalized_prefix = prefix.strip().lower() if sep else ""

    doi_candidate = value if (
        (normalized_prefix == "doi" and value)
        or (not sep and query.lower().startswith("10.") and "/" in query)
    ) else None
    doi_value = normalize_doi(doi_candidate)
    if normalized_prefix == "doi" and not doi_value:
        raise HTTPException(400, "DOI 格式不正确")

    if doi_value:
        rows = (await db.execute(text("""
            (
            SELECT
              rx.id,rx.reaction_smiles,NULL::text AS ord_id,
              COALESCE(NULLIF(rx.source_citation,''),'用户发布') AS dataset_name,
              rx.doi,rx.patent,'doi' AS match_basis
            FROM chemistry.reactions rx
            WHERE lower(rx.doi)=:doi
              AND rx.visibility='public' AND rx.moderation_status='visible'
            ORDER BY rx.id
            LIMIT :limit
            )
            UNION ALL
            (
            SELECT
              rx.id,rx.reaction_smiles,o.reaction_id,d.name,
              rp.doi,COALESCE(rx.patent,rp.patent),'doi' AS match_basis
            FROM (
              SELECT reaction_id,doi,patent
              FROM ord.reaction_provenance
              WHERE lower(doi)=:doi
              ORDER BY reaction_id,id
              LIMIT :limit
            ) rp
            JOIN ord.reaction o ON o.id=rp.reaction_id
            JOIN ord.reaction_map lm ON lm.ord_reaction_id=o.id
            JOIN chemistry.reactions rx ON rx.id=lm.reaction_id
            LEFT JOIN ord.dataset d ON d.id=o.dataset_id
            WHERE rx.visibility='public' AND rx.moderation_status='visible'
            ORDER BY rx.id
            )
            ORDER BY 1
            LIMIT :limit
        """), {"doi": doi_value, "limit": params["limit"]})).fetchall()
        return [
            {
                "id": row[0], "reaction_smiles": row[1], "ord_id": row[2],
                "dataset_name": row[3], "doi": row[4], "patent": row[5],
                "match_basis": row[6],
            }
            for row in rows
        ]

    if normalized_prefix in {"reaction", "rxn"} and value.isdigit():
        clauses.append("rx.id=:reaction_id")
        params["reaction_id"] = int(value)
    elif normalized_prefix == "ord" and value:
        clauses.append("o.reaction_id=:source_id")
        params["source_id"] = value if value.lower().startswith("ord-") else f"ord-{value}"
    elif query.isdigit():
        clauses.append("rx.id=:reaction_id")
        params["reaction_id"] = int(query)
    elif query.lower().startswith("ord-"):
        clauses.append("o.reaction_id=:source_id")
        params["source_id"] = query
    if not clauses:
        return []

    rows = (await db.execute(text(f"""
        SELECT DISTINCT ON (rx.id)
          rx.id,rx.reaction_smiles,o.reaction_id,
          CASE WHEN rx.created_by_user_id IS NOT NULL
               THEN COALESCE(NULLIF(rx.source_citation,''),'用户发布') ELSE d.name END,
          COALESCE(rx.doi,rp.doi),COALESCE(rx.patent,rp.patent),
          CASE
            WHEN rx.id=:reaction_id_hint THEN 'reaction_id'
            WHEN lower(coalesce(o.reaction_id,''))=lower(:source_id_hint) THEN 'ord_id'
            ELSE 'doi'
          END AS match_basis
        FROM chemistry.reactions rx
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id=rx.id
        LEFT JOIN ord.reaction o ON o.id=lm.ord_reaction_id
        LEFT JOIN ord.dataset d ON d.id=o.dataset_id
        LEFT JOIN ord.reaction_provenance rp ON rp.reaction_id=o.id
        WHERE ({' OR '.join(clauses)})
          AND rx.visibility='public' AND rx.moderation_status='visible'
        ORDER BY rx.id,rp.id
        LIMIT :limit
    """), {
        **params,
        "reaction_id_hint": params.get("reaction_id", -1),
        "source_id_hint": params.get("source_id", ""),
    })).fetchall()
    return [
        {
            "id": row[0], "reaction_smiles": row[1], "ord_id": row[2],
            "dataset_name": row[3], "doi": row[4], "patent": row[5],
            "match_basis": row[6],
        }
        for row in rows
    ]


