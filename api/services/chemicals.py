"""化合物查询/拼装服务层 — 自 api/routes.py 下沉, 逻辑零改动(批次3c)。

外部引用者: routes(13端点), tests/test_search.py。
"""

from __future__ import annotations

import json
from typing import Any

# --- Search-path 查询内核 neutral 异常(G2.3D) ---------------------------
# transport-neutral: 只携带 detail, 无 status/header/HTTP 概念。
# 映射唯一发生在 api/routes.py(HTTP)与 api/mcp_server.py(MCP)。
# detail 文本为 c30dfe8 基线契约原文, 逐字保持。


class QueryInputError(Exception):
    """搜索查询输入不合法(结构/标识符)的最小公共基类。"""


class InvalidSmilesError(QueryInputError):
    pass


class SubstructureTooSmallError(QueryInputError):
    pass


class InvalidDoiError(QueryInputError):
    pass


class SubstructureUnavailableError(Exception):
    """结构检索后端暂不可用(慢窗/语句超时), detail 原文保留。"""

from rdkit import Chem
from sqlalchemy import text

from ..chemistry import normalize_doi
from ..core.cache import cache_get, cache_set

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
# locale 名称的唯一来源: name_index 中 (kind, lang, source) = ('name_cn','cn','cb') 的行,
# 镜像 chemical_cb.entry.identity.cn(CB 主中文名, 每化合物至多一条 —— 172,801 行 /
# 172,801 chemical_id)。三元组一起收紧: 将来任何其他 source/lang 落同名 kind 的数据
# 都不得进入主标题, 也不能靠字典序(DISTINCT ON ... ORDER BY name)抢占。
# alias_cn/synonym_en/supplier 是别名/供应商名, 不参与主标题解析。
LOCALIZED_NAME_KIND = "name_cn"
LOCALIZED_NAME_LANG = "cn"
LOCALIZED_NAME_SOURCE = "cb"


def name_query_width(query: str) -> int:
    """名称查询宽度: CJK 计 2, 其余计 1。用于最短长度判定。"""
    return sum(2 if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff'
               or '\uac00' <= ch <= '\ud7af' else 1 for ch in query)


def bounded_substructure_smiles(smiles: str) -> str:
    """Reject queries whose result set is effectively unbounded at PubChem scale."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise InvalidSmilesError("无法识别该 SMILES 结构")
    if mol.GetNumHeavyAtoms() < MIN_SUBSTRUCTURE_HEAVY_ATOMS:
        raise SubstructureTooSmallError(f"子结构过小，请至少提供 {MIN_SUBSTRUCTURE_HEAVY_ATOMS} 个非氢原子")
    return smiles


def chemical_dict(row: Any, score: float | None = None) -> dict[str, Any]:
    return {
        "id": row[0],
        "pubchem_cid": row[1],
        "smiles": row[2],
        "pubchem_smiles": row[3],
        "preferred_name": row[4],
        "iupac_name": row[5],
        # locale 名称(name_index kind='name_cn'): 由 attach_localized_names 批量填充;
        # 保持槽位稳定, 任何 payload 形状一致。
        "name_cn": None,
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


async def attach_localized_names(db: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量补 locale 名称到化学 payload, 一次查询覆盖整页。

    只按返回的 id 列表取 (kind,lang,source)=('name_cn','cn','cb') 的行(走
    name_index_chemical_id_idx), 不下发 name_index 全量, 不改变搜索/结构检索
    既有 SQL。三元组缺一不可: 定义里 name_cn 就是"CB identity.cn 主中文名",
    不能由未来其他 source 的同 kind 数据经字典序决定主标题。
    """
    if not items:
        return items
    ids = [row["id"] for row in items if row.get("id") is not None]
    if not ids:
        return items
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (chemical_id) chemical_id, name
        FROM chemistry.name_index
        WHERE chemical_id = ANY(:ids)
          AND kind = :kind AND lang = :lang AND source = :source
        ORDER BY chemical_id, name
    """), {
        "ids": ids,
        "kind": LOCALIZED_NAME_KIND,
        "lang": LOCALIZED_NAME_LANG,
        "source": LOCALIZED_NAME_SOURCE,
    })).fetchall()
    localized = {row[0]: row[1] for row in rows}
    for row in items:
        row["name_cn"] = localized.get(row["id"])
    return items


async def fetch_chemicals(db: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (await db.execute(text(sql), params)).fetchall()
    items = [chemical_dict(row, row[17] if len(row) > 17 else None) for row in rows]
    return await attach_localized_names(db, items)


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
        raise InvalidDoiError("DOI 格式不正确")

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




async def load_public_config(db: Any) -> dict[str, dict[str, Any]]:
    """公开系统配置(analytics/ads/site/branding)。自 routes.public_config 下沉, 逻辑零改动(批次5a)。"""
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
    return result

async def load_datasets(db: Any, page: int, page_size: int) -> list[dict[str, Any]]:
    """ORD 数据集分页。自 routes.datasets 下沉, 逻辑零改动(批次5a)。"""
    rows = (await db.execute(text("""
        SELECT id, dataset_id, name, description, num_reactions, submitted_at
        FROM ord.dataset ORDER BY num_reactions DESC NULLS LAST, id
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": (page - 1) * page_size})).fetchall()
    return [{
        "id": row[0], "dataset_id": row[1], "name": row[2], "description": row[3],
        "reaction_count": row[4], "submitted_at": row[5],
    } for row in rows]

async def load_sitemap_reactions(db: Any, after_id: int, limit: int) -> dict[str, Any]:
    """站点地图用公开反应ID keyset 分页。自 routes.sitemap_reactions 下沉, 逻辑零改动(批次5a)。"""
    rows = (await db.execute(text("""
        SELECT id, updated_at FROM chemistry.reactions
        WHERE id > :after_id AND visibility='public' AND moderation_status='visible'
        ORDER BY id LIMIT :limit
    """), {"after_id": after_id, "limit": limit})).fetchall()
    return {
        "reactions": [{"id": row[0], "updated_at": row[1]} for row in rows],
        "last_id": rows[-1][0] if rows else None,
    }


async def load_synonyms_page(db: Any, chemical_id: int, offset: int, page_size: int) -> tuple[int | None, Any]:
    """同义词分页(total, values)。自 routes.chemical_synonyms 下沉, 逻辑零改动(批次5a)。"""
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
        return None, None
    return int(row[0]), row[1]


SUBSTRUCTURE_SNAPSHOT_CAP = 250

SUBSTRUCTURE_SNAPSHOT_TTL = 300
SUBSTRUCTURE_SNAPSHOT_SLOW_TTL = 60   # 0915: 超时负缓存窗口


def _is_statement_timeout(exc: Exception) -> bool:
    """语句超时判定: asyncpg QueryCanceledError 经 SQLAlchemy 包装成
    DBAPIError, 检查链条(orig / __cause__)上任意一层。"""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ in ("QueryCanceledError", "QueryCanceled"):
            return True
        if getattr(cur, "code", None) == "57014":  # PG SQLSTATE query_canceled
            return True
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
    return False


def _snapshot_total(ids: list[int], offset: int, page_size: int,
                    snapshot_capped: bool | None = None) -> int | None:
    """snapshot 分页 total 语义(0912, 只修元数据):

    - snapshot 未满 cap ⇒ 它就是本次检索的完整匹配集 → total 恒为 len(ids);
      (0914 #4: cap 判定必须用排除自身前的 snapshot 长度 — 排除后 249 会被
      误判成"未触顶的精确总数", 而真实匹配可能远超 cap。)
    - snapshot 满 cap(=产品上限) ⇒ 中途页 None("更多结果" = 上限内还有);
      到 snapshot 尾部必须收敛: 最后一页给 len(ids), 即"本次结构检索返回的
      匹配数(已达上限)"。绝不把 250 冒充数据库真实匹配总数 — 上限标记由响应
      的 capped 字段单独承载。
    """
    capped = snapshot_capped if snapshot_capped is not None \
        else len(ids) >= SUBSTRUCTURE_SNAPSHOT_CAP
    end_of_snapshot = len(ids[offset:offset + page_size]) < page_size or \
        offset + page_size >= len(ids)
    if not capped or end_of_snapshot:
        return len(ids)
    return None


async def substructure_snapshot(db: Any, smiles: str,
                                cap: int = SUBSTRUCTURE_SNAPSHOT_CAP) -> list[int]:
    """有上限的子结构候选 ID snapshot(无序 GiST + Python 排序 + Redis 缓存)。

    P0(0912 审计): 任何 `mol @> ... ORDER BY c.id` 形态都会被 planner 换成
    pkey 顺序扫(1.24 亿行), GiST 失效 → 高选择性/深页 8s 超时。这里去掉 SQL
    排序: GiST 无 ORDER BY 必被选中(生产 EXPLAIN 实证), 排序在 Python 做。

    分页语义随之改变(0912): 不再用 SQL OFFSET 逐页重扫候选集(深页必然重复
    做昂贵计算), 而是首次 cache miss 取一次 snapshot 并整体缓存 TTL 300s,
    后续页只对同一 snapshot 切片 → 页间无重叠/无漏项, TTL 内分页完全确定。
    """
    key = f"v3:substructure-snapshot:{cap}:{smiles}"
    cached = await cache_get(key)
    if isinstance(cached, list):
        return [int(value) for value in cached]
    # 0915 性能收口(超时负缓存): 稀疏/中低选择性查询在 1.24 亿行 GiST 上
    # 凑满 cap 可能 >8s(生产 EXPLAIN 实证 6.5s@250, 冷缓存更差)。旧形态
    # 打满 8s → 503 且零缓存, TTL 300s 内同一 SMILES 每次请求都全价重扫,
    # 慢查询可连环占满结构租约(全局并发 4)。注意语句被 cancel 时已扫行全部
    # 丢弃(asyncpg QueryCanceledError), 部分结果不可得 — 只能负缓存:
    # 打满一次后 60s 内同 SMILES 直接快速 503, 不再进库。数据不变、缓存
    # 变热后自然恢复(60s 窗口滑过即重试)。
    slow = await cache_get(key + ":slow")
    if slow:
        raise SubstructureUnavailableError("该子结构检索过慢，请稍后重试或使用更精确的结构")
    await db.execute(text("SET LOCAL statement_timeout = '8s'"))
    try:
        rows = (await db.execute(text("""
            SELECT id FROM chemistry.chemicals c
            WHERE c.mol @> mol_from_smiles(:smiles)
            LIMIT :cap
        """), {"smiles": smiles, "cap": cap})).fetchall()
    except Exception as exc:
        if not _is_statement_timeout(exc):
            raise
        await db.rollback()
        await cache_set(key + ":slow", True, ttl=SUBSTRUCTURE_SNAPSHOT_SLOW_TTL)
        raise SubstructureUnavailableError("查询超时，请使用更精确的结构")
    ids = sorted(int(row[0]) for row in rows)
    await cache_set(key, ids, ttl=SUBSTRUCTURE_SNAPSHOT_TTL)
    return ids


async def hydrate_chemicals(db: Any, ids: list[int]) -> list[dict[str, Any]]:
    """按给定 ID 顺序 hydrate 化学行(snapshot 分页用; 主键点查, 无 OFFSET 扫描)。"""
    if not ids:
        return []
    items = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT}
        FROM chemistry.chemicals c
        WHERE c.id = ANY(:ids)
    """, {"ids": list(ids)})
    order = {value: index for index, value in enumerate(ids)}
    items.sort(key=lambda item: order.get(item["id"], len(order)))
    return items


async def fill_detail_context(db: Any, result: dict[str, Any], chemical_id: int, user_id: int) -> None:
    """详情页上下文填充(synonyms/reaction_count/follows)。自 routes.chemical_detail 下沉, 逻辑零改动(批次5a)。"""
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
    """), {"id": chemical_id, "user_id": user_id})).fetchone()
    result["follower_count"] = int(follow_row[0])
    result["is_following"] = bool(follow_row[1])


# --- Chemical Detail 共享编排(G2.4B) ------------------------------------
# HTTP/MCP 唯一 application flow; adapter 只保留 transport 解析/auth/
# projection/错误映射。fetch 顺序与 c30dfe8 基线逐字一致。


class ChemicalNotFoundError(Exception):
    """chemical_id 无对应行的 neutral 语义错误(detail 固定基线原文)。"""


async def get_chemical_detail(
    db: Any,
    chemical_id: int,
    *,
    actor_id: int | None,
    priority: int,
) -> dict[str, Any]:
    """返回 canonical full business detail(未做 display 投影)。

    flow(基线原文顺序):
      fetch_chemicals → not-found → fill_detail_context(actor_id|0)
      → enqueue_chemical_if_needed(priority, allow_refresh=True)
      → job commit → details → enrichment status/job_id 组装。
    priority 由 adapter 按既有 policy(80=actor/50=匿名)显式传入;
    MCP 当前恒匿名 priority=50。
    """
    from .enrichment import enqueue_chemical_if_needed

    rows = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c WHERE c.id=:id
    """, {"id": chemical_id})
    if not rows:
        raise ChemicalNotFoundError("化合物不存在")
    result = rows[0]
    await fill_detail_context(db, result, chemical_id,
                               actor_id if actor_id is not None else 0)
    details, job_id, needs_refresh = await enqueue_chemical_if_needed(
        db,
        chemical_id,
        priority=priority,
        allow_refresh=True,
    )
    if job_id is not None:
        await db.commit()
    result["details"] = details
    result["enrichment"] = {
        "status": "queued" if job_id is not None else ("stale" if needs_refresh else "current"),
        "job_id": job_id,
    }
    return result
