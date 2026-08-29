"""Public read API for the autonomous chemicals and reactions data model."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from rdkit import Chem
from sqlalchemy import text

from .cache import cache_get, cache_set
from .chemistry import CAS_RE, DTXSID_RE, INCHIKEY_RE, canonicalize_smiles, normalize_doi
from .config import settings
from .database import get_db
from .name_index import normalize_name
from .rate_limit import enforce
from .enrichment import (
    DEFAULT_SECTIONS,
    display_details,
    enqueue_chemical_if_needed,
)
from .security import Actor, internal_or_actor

router = APIRouter(tags=["chemistry"])


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


@router.get("/stats")
async def stats(actor: Actor | None = Depends(internal_or_actor), db=Depends(get_db)):
    cached = await cache_get("v1:stats:exact")
    if cached:
        return cached
    row = (await db.execute(text("""
        SELECT
          (SELECT exact_count FROM chemistry.statistics WHERE metric='chemicals'),
          (SELECT exact_count FROM chemistry.statistics WHERE metric='reactions'),
          (SELECT count(*) FROM ord.dataset),
          (SELECT count(*) FROM ingest.reaction_rdkit_failures)
    """))).one()
    data = {
        "chemicals": max(row[0], 0), "reactions": max(row[1], 0),
        "datasets": row[2], "rdkit_failures": row[3],
    }
    await cache_set("v1:stats:exact", data, ttl=3600)
    return data


@router.get("/config")
async def public_config(actor: Actor | None = Depends(internal_or_actor), db=Depends(get_db)):
    """公开系统配置，供前端 layout 动态渲染。"""
    cache_key = "config:public:all"
    cached = await cache_get(cache_key)
    if cached:
        return cached
    rows = (await db.execute(text("""
        SELECT namespace, key, value FROM community.system_config
        WHERE namespace IN ('analytics', 'ads', 'site', 'branding')
        ORDER BY namespace, key
    """))).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for r in rows:
        ns = r[0]
        key = r[1]
        val = r[2]
        if isinstance(val, str):
            val = json.loads(val)
        result.setdefault(ns, {})[key] = val
    await cache_set(cache_key, result, ttl=300)
    return result


@router.get(
    "/search",
    operation_id="search_chemistry_data",
    summary="统一查询化合物和反应",
)
async def search(
    actor: Actor | None = Depends(internal_or_actor),
    q: str = Query(..., min_length=1, max_length=4000),
    mode: str = Query("exact", pattern="^(exact|substructure|similarity)$"),
    page: int = Query(1, ge=1, le=20),
    page_size: int = Query(30, ge=1, le=100),
    db=Depends(get_db),
):
    """One entry point for names, external identifiers, SMILES and structures."""
    query = q.strip()
    cas_fetch_pending = False  # CAS miss 已入队CB获取(standalone任务)
    # 结构检索登录墙(2026-08-26): GIST 单路 ~400ms 但并发无上限, 爬虫 12 路并发
    # 曾把机器打进 swap 全站僵死. exact 保持匿名(SSR); 结构模式需已鉴权 actor.
    if mode != "exact" and actor is None:
        raise HTTPException(401, "结构检索（子结构/相似度）需要登录或提供 API Token")
    offset = (page - 1) * page_size
    cache_key = f"v2:unified-search:{mode}:{page}:{page_size}:{query}"
    if mode != "exact":
        cached = await cache_get(cache_key)
        if cached:
            return cached
    # Exact searches can include user-created reactions. Keep them live so a
    # create, edit or delete is reflected immediately. Only expensive
    # structure searches use the short-lived shared cache.

    canonical = canonicalize_smiles(query)
    chemicals: list[dict[str, Any]] = []
    total: int | None = None
    clauses: list[str] = []
    params: dict[str, Any] = {}
    try:
        if mode == "exact":
            await db.execute(text("SET LOCAL statement_timeout = '5s'"))
        if mode == "substructure":
            if not canonical:
                raise HTTPException(400, "无法识别该 SMILES 结构")
            canonical = bounded_substructure_smiles(canonical)
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
            chemicals = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT}
                FROM chemistry.chemicals c
                WHERE c.mol @> mol_from_smiles(:smiles)
                ORDER BY c.id
                LIMIT :limit OFFSET :offset
            """, {"smiles": canonical, "limit": page_size, "offset": offset})
            chemicals.sort(key=lambda item: item["id"])
        elif mode == "similarity":
            if not canonical:
                raise HTTPException(400, "无法识别该 SMILES 结构")
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
            chemicals = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT},
                       1 - (c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles)))
                FROM chemistry.chemicals c
                WHERE c.mol IS NOT NULL
                ORDER BY c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles))
                LIMIT :limit OFFSET :offset
            """, {"smiles": canonical, "limit": page_size, "offset": offset})
            chemicals.sort(key=lambda item: item.get("similarity") or 0, reverse=True)
        else:
            clauses = []
            params = {"q": query, "uq": query.upper(), "limit": page_size, "offset": offset}
            name_index_hit = False
            prefix, sep, raw_value = query.partition(":")
            if sep and prefix.lower() in IDENTIFIER_ARRAYS:
                clauses.append(f"c.{IDENTIFIER_ARRAYS[prefix.lower()]} @> ARRAY[:qv]")
                params["qv"] = raw_value.strip()
            elif sep and prefix.lower() == "cid" and raw_value.strip().isdigit():
                clauses.append("c.pubchem_cid = :number")
                params["number"] = int(raw_value)
            elif sep and prefix.lower() == "id" and raw_value.strip().isdigit():
                clauses.append("c.id = :number")
                params["number"] = int(raw_value)
            else:
                if query.isdigit():
                    clauses.extend(["c.id = :number", "c.pubchem_cid = :number"])
                    params["number"] = int(query)
                if CAS_RE.fullmatch(query):
                    clauses.append("c.cas_numbers @> ARRAY[:q]")
                elif INCHIKEY_RE.fullmatch(query.upper()):
                    clauses.append("c.inchikey = :uq")
                elif DTXSID_RE.fullmatch(query):
                    clauses.append("c.dtxsid = :uq")
                elif query.upper().startswith("CHEMBL"):
                    clauses.append("c.chembl_ids @> ARRAY[:q]")
                elif query.upper().startswith("CHEBI:"):
                    clauses.append("c.chebi_ids @> ARRAY[:q]")
                elif canonical:
                    from rdkit import Chem as _Chem
                    _mol = _Chem.MolFromSmiles(canonical)
                    _ik = _Chem.MolToInchiKey(_mol) if _mol else None
                    clauses.append("(c.smiles = :smiles AND c.mol IS NOT NULL)")
                    params["smiles"] = canonical
                    if _ik:
                        clauses.append("c.inchikey = :ik")
                        params["ik"] = _ik
            if clauses:
                chemicals = await fetch_chemicals(db, f"""
                    SELECT {CHEMICAL_SELECT}
                    FROM chemistry.chemicals c
                    WHERE {' OR '.join(clauses)}
                    ORDER BY c.id LIMIT :limit OFFSET :offset
                """, params)
                # CAS miss -> standalone CB 任务(2026-08-27): 只入队不同步拉。
                # 三态: pending=在途 / miss=CB负缓存 / 新入队也返回 pending。
                # 鉴权用户按 actor.id 限流; 匿名(BFF/SSR=loopback)共享全局桶
                # 30/min(BFF 后无真实IP可用, 靠 dedupe+深度闸门兜底)。
                # 限流/入队失败一律降级为不入队, 绝不阻塞搜索响应。
                if (
                    not chemicals and page == 1 and CAS_RE.fullmatch(query)
                ):
                    try:
                        from .cas_externals import (
                            cas_search_state, enqueue_cas_search_fetch,
                        )
                        state = await cas_search_state(db, query)
                        if state == "new":
                            try:
                                identity = (
                                    str(actor.id) if actor is not None
                                    else "anon-shared"
                                )
                                limit = 10 if actor is not None else 30
                                await enforce(
                                    "cas-search-fetch", identity, limit, 60,
                                )
                            except HTTPException:
                                state = "new"  # 限流中: 本次不入队
                            else:
                                enqueued = await enqueue_cas_search_fetch(
                                    db, cas_number=query,
                                )
                                await db.commit()
                                state = "pending" if enqueued else "miss"
                    except Exception:
                        await db.rollback()  # 入队失败不阻塞搜索响应
                        state = "new"
                    if state == "pending":
                        cas_fetch_pending = True
            # SMILES miss -> 建行入库(2026-08-29): canonical 校验通过但库内无行时,
            # 复用反应侧 resolve_or_create_chemical 同套逻辑(本地 RDKit 算结构三件),
            # 本次响应即返回该行. 结构行与反应创建同形态, 不新增入队/限流(结构合法
            # 即行合法, 延伸字段留 PB/CB 自然演进). 建行失败降级为空结果, 不阻塞.
            if not chemicals and page == 1 and canonical and len(query) <= 4000:
                try:
                    from .reactions import resolve_or_create_chemical
                    chemical_id, _created = await resolve_or_create_chemical(db, canonical)
                    created = await fetch_chemicals(db, f"""
                        SELECT {CHEMICAL_SELECT}
                        FROM chemistry.chemicals c WHERE c.id = :id
                    """, {"id": chemical_id})
                    if created:
                        await db.commit()
                        chemicals = created
                    else:
                        await db.rollback()
                except Exception:
                    await db.rollback()  # 建行失败不阻塞搜索响应
            if not chemicals and not canonical and name_query_width(query) >= MIN_FUZZY_NAME_LENGTH:
                # Keep the two trigram indexes independent. A cross-column OR on
                # 124M rows is both slower and less predictable than two bounded scans.
                # CJK 短语跳过前两段: preferred_name/iupac 全英文, 2 字中文的 trigram
                # 索引选择性崩塌(乙醇 bitmap 吐 42 万候选 91s); 中文名只活在这段。
                has_cjk = name_query_width(query) > len(query)
                if not has_cjk:
                    chemicals = await fetch_chemicals(db, f"""
                        SELECT {CHEMICAL_SELECT}
                        FROM chemistry.chemicals c
                        WHERE c.preferred_name ILIKE '%' || :q || '%'
                        ORDER BY c.id LIMIT :limit OFFSET :offset
                    """, {"q": query, "limit": page_size, "offset": offset})
                    if len(chemicals) < page_size:
                        secondary = await fetch_chemicals(db, f"""
                            SELECT {CHEMICAL_SELECT}
                            FROM chemistry.chemicals c
                            WHERE c.iupac_name ILIKE '%' || :q || '%'
                            ORDER BY c.id LIMIT :limit OFFSET :offset
                        """, {"q": query, "limit": page_size, "offset": offset})
                        seen = {item["id"] for item in chemicals}
                        # 相关性排序: preferred_name 命中段排在前, iupac 段追加在后.
                        # 不再按 id 归并排序(id 排序会让低段位命中挤掉精确名匹配).
                        chemicals.extend(item for item in secondary if item["id"] not in seen)
                        chemicals = chemicals[:page_size]
                # 第三段: name_index(中文名/别名/供应商名/synonyms 的派生镜像)。
                # 只在前两段不足一页时下探, 前两路零改动。
                if (has_cjk or len(chemicals) < page_size) and offset == 0:
                    tertiary_ids = (await db.execute(text("""
                        SELECT DISTINCT chemical_id FROM chemistry.name_index
                        WHERE normalized LIKE '%' || :nq || '%'
                        ORDER BY chemical_id LIMIT :limit
                    """), {"nq": normalize_name(query), "limit": page_size})).scalars().all()
                    if tertiary_ids:
                        name_index_hit = True
                        # 合并而非替换: 前两段结果保留, 去重后追加(与第二段同型).
                        # 相关性排序: 段位顺序 = preferred_name > iupac > name_index;
                        # 同义词层(如"Aspirin Impurity C")不得越过精确名命中.
                        seen = {item["id"] for item in chemicals}
                        fresh_ids = [i for i in tertiary_ids if i not in seen]
                        if fresh_ids:
                            more = await fetch_chemicals(db, f"""
                                SELECT {CHEMICAL_SELECT}
                                FROM chemistry.chemicals c
                                WHERE c.id = ANY(:ids)
                                ORDER BY c.id
                            """, {"ids": fresh_ids})
                            chemicals.extend(more)
                            chemicals = chemicals[:page_size]
            elif not chemicals and not canonical and name_query_width(query) < MIN_FUZZY_NAME_LENGTH:
                raise HTTPException(422, "名称查询至少需要 3 个字符（中文至少 2 个字）")

        # 结构模式不跑全量 count: similarity 的 count 与查询词无关(count mol 行),
        # substructure 巨命中 count 在 143 万 mol 行上必超时 — 两者都是注定 3s 白烧.
        # total 语义: 结果不足一页 = 免费精确值(offset+len); 满一页 = None("更多结果").
        if mode in {"substructure", "similarity"}:
            total = offset + len(chemicals) if len(chemicals) < page_size else None
        try:
            if mode == "exact" and not canonical and name_query_width(query) >= MIN_FUZZY_NAME_LENGTH:
                if name_index_hit:
                    pass  # 第三段贡献结果: 两列 count 不覆盖 name_index, 保持 None(更多结果)
                elif clauses:
                    total = (await db.execute(text(f"""
                        SELECT count(*) FROM chemistry.chemicals c
                        WHERE {' OR '.join(clauses)}
                    """), params)).scalar()
                else:
                    await db.execute(text("SET LOCAL statement_timeout = '3s'"))
                    total = (await db.execute(text("""
                        SELECT count(*) FROM chemistry.chemicals c
                        WHERE c.preferred_name ILIKE '%' || :q || '%'
                           OR c.iupac_name ILIKE '%' || :q || '%'
                    """), {"q": query})).scalar()
        except Exception:
            total = None

        reactions = await reaction_lookup(db, query, page_size) if mode == "exact" and page == 1 else []
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, "查询超时，请使用更精确的名称、标识符或结构") from exc

    data: dict[str, Any] = {
        "query": query, "mode": mode, "canonical_smiles": canonical,
        "page": page, "page_size": page_size, "total": total,
        "chemicals": chemicals, "reactions": reactions,
    }
    if cas_fetch_pending:
        data["cas_fetch_pending"] = True  # 前端提示: 正在获取该CAS数据
    if mode != "exact":
        await cache_set(cache_key, data, ttl=300)
    return data


@router.get(
    "/chemicals/{chemical_id}",
    operation_id="get_chemical",
    summary="读取一个化合物记录",
)
async def chemical_detail(
    request: Request,
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    enrich: str = Query("core", pattern="^(core|full)$"),
    display: bool = Query(False),
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    rows = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c WHERE c.id=:id
    """, {"id": chemical_id})
    if not rows:
        raise HTTPException(404, "化合物不存在")
    result = rows[0]
    synonym_row = (await db.execute(text("""
        WITH source AS (
            SELECT CASE WHEN jsonb_typeof(synonyms)='array'
                THEN synonyms ELSE '[]'::jsonb END AS items
            FROM chemistry.chemicals WHERE id=:id
        )
        SELECT jsonb_array_length(items),coalesce((
            SELECT jsonb_agg(value ORDER BY ordinality)
            FROM jsonb_array_elements_text(items) WITH ORDINALITY AS alias(value,ordinality)
            WHERE ordinality<=20
        ),'[]'::jsonb)
        FROM source
    """), {"id": chemical_id})).fetchone()
    result["synonym_count"] = int(synonym_row[0]) if synonym_row else 0
    result["synonyms"] = list(synonym_row[1] or []) if synonym_row else []
    total_reactions = int((await db.execute(text("""
        SELECT count(DISTINCT rc.reaction_id) FROM chemistry.reaction_chemicals rc
        WHERE rc.chemical_id=:id
    """), {"id": chemical_id})).scalar() or 0)
    excluded_reactions = int((await db.execute(text("""
        SELECT count(DISTINCT rc.reaction_id)
        FROM chemistry.reactions rx
        JOIN chemistry.reaction_chemicals rc ON rc.reaction_id=rx.id
        WHERE (rx.visibility<>'public' OR rx.moderation_status<>'visible')
          AND rc.chemical_id=:id
    """), {"id": chemical_id})).scalar() or 0)
    result["reaction_count"] = max(total_reactions - excluded_reactions, 0)
    follow_row = (await db.execute(text("""
        SELECT count(*),EXISTS(
          SELECT 1 FROM community.chemical_follows WHERE chemical_id=:id AND user_id=:user_id
        ) FROM community.chemical_follows WHERE chemical_id=:id
    """), {"id": chemical_id, "user_id": actor.id if actor else 0})).fetchone()
    result["follower_count"] = int(follow_row[0])
    result["is_following"] = bool(follow_row[1])
    details, job_id, needs_refresh = await enqueue_chemical_if_needed(
        db,
        chemical_id,
        sections=FULL_DETAILS_SECTIONS if enrich == "full" else DEFAULT_SECTIONS,
        # 优先级对齐 CB 定论: 80=用户(登录) / 50=后台. 匿名 SSR(爬虫翻页)
        # 不是用户, 不占用户位(2026-08-27 血案: 匿名流量曾以 80 插队灌队列).
        priority=80 if actor is not None else 50,
        request=request,
        actor=actor,
    )
    if job_id is not None:
        await db.commit()
    result["details"] = display_details(details) if display else details
    result["enrichment"] = {
        "status": "queued" if job_id is not None else ("stale" if needs_refresh else "current"),
        "job_id": job_id,
        "requested_sections": list(
            FULL_DETAILS_SECTIONS if enrich == "full" else DEFAULT_SECTIONS
        ),
    }
    return result


@router.get("/chemicals/{chemical_id}/externals", operation_id="get_chemical_externals",
            summary="化合物的中文扩展信息与供应商")
async def chemical_externals(
    request: Request,
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    """CB 扩展读端点: 读库+ensure 驱动(新 CAS 首访同步拉, 超期 worker 刷).

    遵循公开读口径: 无原站标识; 404 = 化合物不存在;
    entry/suppliers 为空 = 该化合物无 CAS 或源站无数据(非错误)。
    """
    from .cas_externals import ensure_externals, sync_fetch_and_store

    row = (await db.execute(text("""
        SELECT id, cas_numbers[1] AS cas FROM chemistry.chemicals WHERE id=:id
    """), {"id": chemical_id})).fetchone()
    if not row:
        raise HTTPException(404, "化合物不存在")
    cas_number = row[1]
    if not cas_number:
        return {"chemical_id": chemical_id, "state": "no_cas",
                "entry": None, "suppliers": []}
    outcome = await ensure_externals(db, chemical_id, cas_number=cas_number)
    if outcome["state"] == "absent":
        # 首访: 同步拉取(3s 预算); 失败入队,本响应出空
        sync = await sync_fetch_and_store(db, chemical_id=chemical_id, cas_number=cas_number)
        if sync and sync["status"] == "ok":
            outcome = await ensure_externals(db, chemical_id, cas_number=cas_number)
        else:
            from .cas_externals import enqueue_cas_job
            job_id = await enqueue_cas_job(
                db, chemical_id=chemical_id, cas_number=cas_number, priority=80,
                request_context={"reason": "sync_failed"},
            )
            await db.commit()
            outcome = {"state": "queued", "entry": None, "suppliers": [],
                       "job_id": job_id}
    return {
        "chemical_id": chemical_id,
        "state": outcome["state"],
        "entry": outcome.get("entry"),
        "suppliers": outcome.get("suppliers") or [],
    }


@router.get("/chemicals/{chemical_id}/synonyms")
async def chemical_synonyms(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor | None = Depends(internal_or_actor),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(100, ge=1, le=500),
    db=Depends(get_db),
):
    offset = (page - 1) * page_size
    row = (await db.execute(text("""
        WITH source AS (
            SELECT CASE WHEN jsonb_typeof(synonyms)='array'
                THEN synonyms ELSE '[]'::jsonb END AS values
            FROM chemistry.chemicals WHERE id=:chemical_id
        )
        SELECT jsonb_array_length(values),coalesce((
            SELECT jsonb_agg(value ORDER BY ordinality)
            FROM jsonb_array_elements_text(values) WITH ORDINALITY AS alias(value,ordinality)
            WHERE ordinality>:offset AND ordinality<=:offset+:page_size
        ),'[]'::jsonb)
        FROM source
    """), {
        "chemical_id": chemical_id,
        "offset": offset,
        "page_size": page_size,
    })).fetchone()
    if not row:
        raise HTTPException(404, "化合物不存在")
    return {
        "chemical_id": chemical_id,
        "total": int(row[0]),
        "page": page,
        "page_size": page_size,
        "synonyms": list(row[1] or []),
    }


@router.get("/chemicals/{chemical_id}/reactions")
async def chemical_reactions(
    chemical_id: int,
    actor: Actor | None = Depends(internal_or_actor),
    role: str = Query("any", pattern="^(any|reactant|reagent|solvent|catalyst|product)$"),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    total, items = await reaction_summaries(db, [chemical_id], role, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "reactions": items}


@router.get("/chemicals/{chemical_id}/substructure")
async def chemical_substructure(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    page: int = Query(1, ge=1, le=20),
    page_size: int = Query(30, ge=1, le=100),
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    cache_key = f"v2:substructure:{chemical_id}:{page}:{page_size}"
    # 结构检索登录墙: 同 /api/search 的 mode!=exact 分支(见该处注释)
    if actor is None:
        raise HTTPException(401, "结构检索（子结构）需要登录或提供 API Token")
    cached = await cache_get(cache_key)
    if cached:
        return cached

    smiles = (await db.execute(text(
        "SELECT smiles FROM chemistry.chemicals WHERE id=:id AND mol IS NOT NULL"
    ), {"id": chemical_id})).scalar()
    if not smiles:
        raise HTTPException(404, "化合物没有可检索结构")
    smiles = bounded_substructure_smiles(smiles)
    offset = (page - 1) * page_size
    await db.execute(text("SET LOCAL statement_timeout = '8s'"))
    items = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT}
        FROM chemistry.chemicals c
        WHERE c.mol @> mol_from_smiles(:smiles) AND c.id<>:id
        ORDER BY c.id
        LIMIT :limit OFFSET :offset
    """, {"id": chemical_id, "smiles": smiles, "limit": page_size, "offset": offset})
    # Preserve the RDKit GiST plan; see the same rule in the public search.
    items.sort(key=lambda item: item["id"])
    # 不跑全量 count(143 万 mol 行上巨命中必超时白烧): 不足一页=免费精确值, 满页=None("更多结果").
    total = offset + len(items) if len(items) < page_size else None
    data = {"page": page, "page_size": page_size, "total": total, "chemicals": items}
    await cache_set(cache_key, data, ttl=300)
    return data


@router.get("/chemicals/{chemical_id}/similarity")
async def chemical_similarity(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    threshold: float = Query(0.7, ge=0.4, le=1.0),
    page: int = Query(1, ge=1, le=20),
    page_size: int = Query(30, ge=1, le=100),
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    cache_key = f"v2:similarity:{chemical_id}:{threshold}:{page}:{page_size}"
    # 结构检索登录墙: 同 /api/search 的 mode!=exact 分支(见该处注释)
    if actor is None:
        raise HTTPException(401, "结构检索（相似度）需要登录或提供 API Token")
    cached = await cache_get(cache_key)
    if cached:
        return cached

    smiles = (await db.execute(text(
        "SELECT smiles FROM chemistry.chemicals WHERE id=:id AND mol IS NOT NULL"
    ), {"id": chemical_id})).scalar()
    if not smiles:
        raise HTTPException(404, "化合物没有可检索结构")
    offset = (page - 1) * page_size
    await db.execute(text("SET LOCAL statement_timeout = '8s'"))
    items = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT},
               1 - (c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles)))
        FROM chemistry.chemicals c
        WHERE c.mol IS NOT NULL AND c.id<>:id
        ORDER BY c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles))
        LIMIT :limit OFFSET :offset
    """, {"id": chemical_id, "smiles": smiles, "limit": page_size, "offset": offset})
    items = [item for item in items if (item.get("similarity") or 0) >= threshold]
    data = {"threshold": threshold, "page": page, "page_size": page_size, "total": len(items), "chemicals": items}
    await cache_set(cache_key, data, ttl=300)
    return data


@router.get(
    "/reactions/{reaction_id}",
    operation_id="get_reaction",
    summary="读取一个反应记录",
)
async def reaction_detail(
    reaction_id: int,
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    viewer_id = actor.id if actor else 0
    viewer_is_admin = bool(actor and actor.role == "admin")
    base = (await db.execute(text("""
        SELECT rx.id,rx.reaction_smiles,rx.visibility,rx.moderation_status,
               rx.created_by_user_id,rx.created_at,rx.updated_at,
               COALESCE(NULLIF(rx.procedure_details,''),rn.procedure_details),
               COALESCE(NULLIF(rx.safety_notes,''),rn.safety_notes),
               COALESCE(rx.ph,cond.ph),COALESCE(NULLIF(rx.conditions_detail,''),cond.details),
               rx.temperature_value,rx.temperature_unit,rx.duration_value,rx.duration_unit,
               rx.atmosphere,rx.pressure_value,rx.pressure_unit,rx.workup_details,
               rx.source_type,COALESCE(NULLIF(rx.doi,''),rp.doi),
               COALESCE(NULLIF(rx.patent,''),rp.patent),
               COALESCE(NULLIF(rx.source_url,''),rp.publication_url),
               CASE WHEN rx.created_by_user_id IS NOT NULL
                    THEN rx.source_citation ELSE d.name END,
               rx.note,o.id,o.reaction_id,cond.reflux,
               u.username,u.display_name,u.avatar_path,
               (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=rx.id),
               EXISTS(SELECT 1 FROM community.reaction_follows
                      WHERE reaction_id=rx.id AND user_id=:viewer_id)
        FROM chemistry.reactions rx
        LEFT JOIN community.users u ON u.id=rx.created_by_user_id
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id=rx.id
        LEFT JOIN ord.reaction o ON o.id=lm.ord_reaction_id
        LEFT JOIN ord.dataset d ON d.id=o.dataset_id
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_provenance p WHERE p.reaction_id=o.id ORDER BY p.id LIMIT 1) rp ON true
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_notes n WHERE n.reaction_id=o.id ORDER BY n.id LIMIT 1) rn ON true
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_conditions c WHERE c.reaction_id=o.id ORDER BY c.id LIMIT 1) cond ON true
        WHERE rx.id=:id
          AND (:is_admin OR rx.created_by_user_id=:viewer_id
               OR (rx.visibility='public' AND rx.moderation_status='visible'))
    """), {"id": reaction_id, "viewer_id": viewer_id, "is_admin": viewer_is_admin})).fetchone()
    if not base:
        raise HTTPException(404, "反应不存在")

    participants = (await db.execute(text(f"""
        SELECT {CHEMICAL_SELECT}, rc.role,rc.occurrence_count,rc.amount_value,rc.amount_unit,
               rc.equivalents,rc.concentration_value,rc.concentration_unit,rc.yield_percent
        FROM chemistry.reaction_chemicals rc
        JOIN chemistry.chemicals c ON c.id=rc.chemical_id
        WHERE rc.reaction_id=:id
        ORDER BY CASE rc.role WHEN 'REACTANT' THEN 1 WHEN 'REAGENT' THEN 2
                 WHEN 'CATALYST' THEN 3 WHEN 'SOLVENT' THEN 4 WHEN 'PRODUCT' THEN 5 ELSE 6 END,
                 c.id
    """), {"id": reaction_id})).fetchall()
    compounds = []
    for row in participants:
        item = chemical_dict(row)
        item.update(
            role=row[17],occurrence_count=row[18],amount_value=row[19],amount_unit=row[20],
            equivalents=row[21],concentration_value=row[22],concentration_unit=row[23],
            yield_percent=clean_float(row[24]),
        )
        compounds.append(item)

    temperature = (await db.execute(text("""
        SELECT t.value, t.units::text
        FROM ord.reaction_map lm
        JOIN ord.reaction_conditions rc ON rc.reaction_id=lm.ord_reaction_id
        JOIN ord.temperature_conditions tc ON tc.reaction_conditions_id=rc.id
        JOIN ord.temperature t ON t.temperature_conditions_id=tc.id
        WHERE lm.reaction_id=:id AND t.value IS NOT NULL ORDER BY t.id LIMIT 1
    """), {"id": reaction_id})).fetchone()
    workup = (await db.execute(text("""
        SELECT rw.type::text, rw.details, rw.keep_phase, rw.target_ph
        FROM ord.reaction_map lm
        JOIN ord.reaction_workup rw ON rw.reaction_id=lm.ord_reaction_id
        WHERE lm.reaction_id=:id ORDER BY rw.id
    """), {"id": reaction_id})).fetchall()
    yields = (await db.execute(text("""
        SELECT pc.chemical_id, max(p.value)
        FROM ord.reaction_map lm
        JOIN ord.reaction_outcome ro ON ro.reaction_id=lm.ord_reaction_id
        JOIN ord.product_compound pc ON pc.reaction_outcome_id=ro.id
        JOIN ord.product_measurement pm ON pm.product_compound_id=pc.id AND pm.type='YIELD'
        JOIN ord.percentage p ON p.product_measurement_id=pm.id
        WHERE lm.reaction_id=:id AND pc.chemical_id IS NOT NULL
        GROUP BY pc.chemical_id
    """), {"id": reaction_id})).fetchall()
    yield_map = {row[0]: clean_float(row[1], round_digits=3) for row in yields}
    for item in compounds:
        if item["role"] == "PRODUCT" and item["yield_percent"] is None:
            item["yield_percent"] = yield_map.get(item["id"])

    conditions_detail = base[10]
    if conditions_detail and conditions_detail.strip().lower().startswith("see reaction.notes"):
        conditions_detail = None

    temp_value = clean_float(base[11])
    temp_unit = base[12]
    if temp_value is None and temperature:
        temp_value = clean_float(temperature[0])
        temp_unit = temperature[1]
    temperature_out = (
        {"value": temp_value, "unit": temp_unit}
        if temp_value is not None
        else None
    )

    return {
        "id": base[0], "reaction_smiles": base[1], "visibility": base[2],
        "moderation_status": base[3], "created_at": base[5], "updated_at": base[6],
        "ord_record_id": base[25], "ord_id": base[26], "dataset_name": base[23],
        "source_type": base[19], "doi": base[20], "patent": base[21],
        "publication_url": base[22], "source_citation": base[23],
        "procedure_details": base[7], "safety_notes": base[8],
        "reflux": base[27], "ph": base[9], "conditions_detail": conditions_detail,
        "temperature": temperature_out,
        "duration": ({"value": base[13], "unit": base[14]} if base[13] is not None else None),
        "atmosphere": base[15],
        "pressure": ({"value": base[16], "unit": base[17]} if base[16] is not None else None),
        "workup_details": base[18], "note": base[24],
        "creator": ({"username": base[28], "display_name": base[29], "avatar_url": base[30]}
                    if base[28] else None),
        "is_owner": base[4] == viewer_id and base[4] is not None,
        "follower_count": int(base[31]), "is_following": bool(base[32]),
        "participants": compounds,
        "workup": [
            {"type": row[0], "details": row[1], "keep_phase": row[2], "target_ph": row[3]}
            for row in workup
        ],
    }


@router.get("/datasets")
async def datasets(
    actor: Actor | None = Depends(internal_or_actor),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(20, ge=1, le=50), db=Depends(get_db)
):
    rows = (await db.execute(text("""
        SELECT id, dataset_id, name, description, num_reactions, submitted_at
        FROM ord.dataset ORDER BY num_reactions DESC NULLS LAST, id
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": (page - 1) * page_size})).fetchall()
    return [{
        "id": row[0], "dataset_id": row[1], "name": row[2], "description": row[3],
        "reaction_count": row[4], "submitted_at": row[5],
    } for row in rows]


@router.get("/sitemap/reactions")
async def sitemap_reactions(
    actor: Actor | None = Depends(internal_or_actor),
    after_id: int = Query(0, ge=0), limit: int = Query(50000, ge=1, le=50000), db=Depends(get_db)
):
    """Keyset-paginated public reaction IDs for sitemap generation."""
    rows = (await db.execute(text("""
        SELECT id, updated_at FROM chemistry.reactions
        WHERE id > :after_id AND visibility='public' AND moderation_status='visible'
        ORDER BY id LIMIT :limit
    """), {"after_id": after_id, "limit": limit})).fetchall()
    return {
        "reactions": [{"id": row[0], "updated_at": row[1]} for row in rows],
        "last_id": rows[-1][0] if rows else None,
    }
