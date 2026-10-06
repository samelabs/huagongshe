"""统一搜索查询构造服务层 — 自 api/routes.py 下沉, 逻辑零改动(批次5a)。
G2.3 final: transport-neutral 化 —— SearchError(kind, detail) 语义类别,
      run_search_query 的 DB 查询/分页/领域校验主体不变。

外部引用者: routes.search(HTTP adapter)/ mcp_server.search_chemistry_data(MCP)。
禁止 import: fastapi/mcp/HTTPException/Request/Response/ToolError/Context。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ..chemistry import CAS_RE, DTXSID_RE, INCHIKEY_RE
from ..core.rate_limit import enforce  # smiles-create 副作用闸门(0914 #5)
from .chemicals import (
    CHEMICAL_SELECT, IDENTIFIER_ARRAYS, MIN_FUZZY_NAME_LENGTH,
    InvalidDoiError, InvalidSmilesError, SubstructureTooSmallError,
    SubstructureUnavailableError,
    bounded_substructure_smiles, fetch_chemicals, name_query_width,
    reaction_lookup,
)
from .name_index import normalize_name


# 语义类别(G2.3 final): service 只表达业务语义, 不含 HTTP status/header。
# HTTP adapter 维护唯一映射 kind→HTTP status; MCP 只用 detail。
SUBSTRUCTURE_TOO_SMALL = "substructure_too_small"  # G2.3D: 合法结构但重原子过小(422 语义)
INVALID_DOI = "invalid_doi"  # G2.3D: DOI 前缀输入格式不合法(400 语义)
INVALID_STRUCTURE = "invalid_structure"    # 无法识别该 SMILES 结构
QUERY_TOO_SHORT = "query_too_short"        # 名称查询长度不足
BACKEND_UNAVAILABLE = "backend_unavailable"  # 查询超时/后端不可用


class SearchError(Exception):
    """transport-neutral 搜索业务错误(G2.3 final): 只携带语义类别 + detail。
    HTTP adapter 映射 kind→HTTPException(detail 逐字);
    MCP adapter 映射 ToolError(detail)。不含 status/status_code/header。"""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail

def cjk_char_count(value: str) -> int:
    """CJK 字符计数(Han/Hiragana-Katakana/Hangul), 与 name_query_width 同字符域。"""
    return sum(
        1 for ch in value
        if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff"
        or "\uac00" <= ch <= "\ud7af"
    )


def is_two_cjk_query(nq: str) -> bool:
    """normalized query 恰好由两个 CJK 字符组成(如 甲醇)。混合查询(甲醇A/甲醇-d4)为 False。"""
    return len(nq) == 2 and cjk_char_count(nq) == 2


def allows_substring_fallback(nq: str) -> bool:
    """是否允许 tier3 substring fallback: 复用既有最短名称契约(width), 且非纯两字 CJK。"""
    return (
        name_query_width(nq) >= MIN_FUZZY_NAME_LENGTH
        and not is_two_cjk_query(nq)
    )


# ---- 名称搜索统一契约(Search System Governance, 2026-09-13) ----
# fuzzy substring 的 DB 侧资格: normalize 后实际字符数 >= 3(trigram 选择性下限)。
# 与 query acceptance(name_query_width >= MIN_FUZZY_NAME_LENGTH)分开:
# A甲/甲A/甲醇 合法但 exact-only; AB 在入口即拒; 苯甲酸/benzoic 可 fuzzy。
MIN_FUZZY_SUBSTR_CHARS = 3

# fuzzy/exact 候选窗口的绝对上限。
# 推导自真实 API 上限(2026-09-13 取证): REST /search page≤20 × page_size≤100
# → 最大 offset=1900, 最大翻页边界=2000; MCP search_chemistry_data 同钳制
# (page≤20, page_size≤100)。上限 = 2000 + 1(has_more 探测) = 2001。
# 实际每页窗口是动态 deterministic 前缀: window = min(offset+page_size+1,
# 上限) —— page1 只付 31 的成本, 深页按需增长, 稳定性由 source SQL 的
# ORDER BY id 前缀契约保证(W31 ⊆ W61 ⊆ W91, 生产实测锁), 不是无序窗口。
FUZZY_CANDIDATE_CAP = 2001


def allows_fuzzy_substring(nq: str) -> bool:
    """fuzzy substring 的数据库资格: normalize 后实际字符数 >= 3。"""
    return len(nq) >= MIN_FUZZY_SUBSTR_CHARS


def candidate_window(offset: int, page_size: int) -> int:
    """deterministic 候选前缀窗口: offset+page_size+1, 受 API 最大边界约束。"""
    return min(offset + page_size + 1, FUZZY_CANDIDATE_CAP)


async def run_name_search(
    db: Any, query: str, page_size: int, offset: int,
) -> tuple[list[dict[str, Any]], bool]:
    """统一名称候选流: exact 聚合短路 → fuzzy deterministic 统一分页。

    返回 (chemicals, has_more)。
    - exact 阶段: 三个来源(preferred/iupac/name_index)全部独立 bounded 等值
      查询(窗口=offset+page_size+1 的 deterministic 前缀), union → dedupe
      chemical_id → tier rank → chemical_id 确定性排序; 任意来源有 exact
      候选即返回 exact stream, 不进 fuzzy(字段 tier 只决定 rank, 不决定
      集合资格 —— 不同实体可通过不同字段 exact 命中)。
    - fuzzy 阶段(仅 exact 全 miss 且 allows_fuzzy_substring): 三个来源各取
      同一 deterministic 前缀窗口(window=offset+page_size+1 ≤ cap, ID-only
      + ORDER BY id, 生产实测热态 90-800ms), Python 侧 去重 → tier rank →
      chemical_id 升序 → 统一 pagination。与旧实现的根本区别: 旧版是无
      ORDER BY 的动态 LIMIT(依赖 planner 返回顺序, 不稳定); 本版 ORDER BY
      前缀契约保证 W_n ⊆ W_{n+1}(生产实测锁), 深页只是更长前缀。
      page1 只付 window=31 的成本, 不为理论深页预付; 深页(2001 级)冷缓存
      可能撞 5s 闸, 属 deep-page bounded debt(现有 503 兜底), 不引入 cache。
    - has_more = 统一候选流长度 > offset+page_size, 无第二条 count SQL。
    """
    nq = normalize_name(query)
    window = candidate_window(offset, page_size)

    # ---- 阶段 1: exact-name candidate aggregation (等值, bounded 前缀) ----
    exact_ranked: list[tuple[int, int]] = []  # (tier_rank, chemical_id)
    exact_seen: set[int] = set()

    async def _ids(sql: str, params: dict[str, Any]) -> list[int]:
        rows = (await db.execute(text(sql), params)).scalars().all()
        return [int(r) for r in rows]

    # 三个来源全部独立查询(不 short-circuit 跳过); exact 同样只取前缀窗口。
    preferred_exact = await _ids(
        "SELECT c.id FROM chemistry.chemicals c"
        " WHERE c.preferred_name = ANY(:variants) ORDER BY c.id LIMIT :window",
        {"variants": _exact_variants(query), "window": window},
    )
    iupac_exact = await _ids(
        "SELECT c.id FROM chemistry.chemicals c"
        " WHERE c.iupac_name = ANY(:variants) ORDER BY c.id LIMIT :window",
        {"variants": _exact_variants(query), "window": window},
    )
    name_index_exact = await _ids(
        "SELECT DISTINCT chemical_id FROM chemistry.name_index"
        " WHERE normalized = :nq ORDER BY chemical_id LIMIT :window",
        {"nq": nq, "window": window},
    )
    for rank, tier_ids in enumerate((preferred_exact, iupac_exact, name_index_exact), start=1):
        for cid in tier_ids:
            if cid not in exact_seen:
                exact_seen.add(cid)
                exact_ranked.append((rank, cid))
    exact_ranked.sort(key=lambda item: (item[0], item[1]))

    if exact_ranked:
        page_rows = [cid for _rank, cid in exact_ranked[offset:offset + page_size]]
        has_more = len(exact_ranked) > offset + page_size
        if page_rows:
            # hydrate 保留候选 rank 顺序: SQL 不再决定最终顺序, 取回后按
            # page_rows(tier rank + id)原顺序重组 —— 跨 tier id 逆序不被抹平。
            rows = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT}
                FROM chemistry.chemicals c
                WHERE c.id = ANY(:ids)
            """, {"ids": page_rows})
            by_id = {row["id"]: row for row in rows}
            hydrated = [by_id[cid] for cid in page_rows if cid in by_id]
            return hydrated, has_more
        return [], False

    # ---- 阶段 2: fuzzy deterministic 统一候选流 (仅 exact 全 miss) ----
    if not allows_fuzzy_substring(nq):
        return [], False

    # ID-only deterministic 前缀: 每来源 ORDER BY id + 动态窗口(≤cap), 不取宽行。
    tier1 = await _ids(
        "SELECT c.id FROM chemistry.chemicals c"
        " WHERE c.preferred_name ILIKE '%' || :q || '%'"
        " ORDER BY c.id LIMIT :window",
        {"q": query, "window": window},
    )
    tier2 = await _ids(
        "SELECT c.id FROM chemistry.chemicals c"
        " WHERE c.iupac_name ILIKE '%' || :q || '%'"
        " ORDER BY c.id LIMIT :window",
        {"q": query, "window": window},
    )
    tier3 = await _ids(
        "SELECT DISTINCT chemical_id FROM chemistry.name_index"
        " WHERE normalized LIKE '%' || :nq || '%'"
        " ORDER BY chemical_id LIMIT :window",
        {"nq": nq, "window": window},
    )
    # 去重 → rank(tier 顺序) → chemical_id 升序 → 统一 pagination
    ranked: list[tuple[int, int]] = []  # (rank, chemical_id)
    dedup: set[int] = set()
    for rank, tier_ids in enumerate((tier1, tier2, tier3), start=1):
        for cid in tier_ids:
            if cid not in dedup:
                dedup.add(cid)
                ranked.append((rank, cid))
    ranked.sort(key=lambda item: (item[0], item[1]))
    page_rows = [cid for _rank, cid in ranked[offset:offset + page_size]]
    has_more = len(ranked) > offset + page_size
    if page_rows:
        # hydrate 保留候选 rank 顺序(与 exact 阶段同法): SQL 顺序不参与最终排序。
        rows = await fetch_chemicals(db, f"""
            SELECT {CHEMICAL_SELECT}
            FROM chemistry.chemicals c
            WHERE c.id = ANY(:ids)
        """, {"ids": page_rows})
        by_id = {row["id"]: row for row in rows}
        hydrated = [by_id[cid] for cid in page_rows if cid in by_id]
        return hydrated, has_more
    return [], False


def _exact_variants(query: str) -> list[str]:
    """等值命中的大小写变体(存储为原大小写; title/lower/upper 覆盖主流形态)。

    不新建索引、不改存储; equality 走现有 trgm 索引(实测 7-266ms)。
    """
    base = query.strip()
    return list({base, base.lower(), base.upper(), base.title()})


async def execute_search(
    db, query: str, mode: str, *, threshold: float, page: int, page_size: int,
    actor_id: int | None,
):
    """共享搜索编排(G2.3 final): HTTP/MCP 唯一 application pipeline。

    职责: offset/缓存键/cache_get/结构闸门/canonicalize/run_search_query/
    cache_set(ttl=300)/structure_exit(finally)/has_more/capped/结果组装。
    adapter 只保留 transport 解析/校验/auth/会话获取/错误映射。

    顺序(与基线逐字一致):
      exact          → 无 cache 无 gate, 直接 canonicalize+query(live);
      结构模式 cache miss → cache_get → structure_enter → canonicalize
                       → run_search_query → cache_set(300) → structure_exit。
    结构闸门异常(RateLimited/LimiterUnavailable/ResourceBusy, G2.R neutral)
    原样冒泡, 由各 adapter 映射; 不得在 service 转 HTTP/ToolError。
    threshold 由 adapter 完成各自 transport 语义(HTTP 3位契约/MCP clamp)后传入。
    """
    import asyncio as _asyncio

    from ..chemistry import canonicalize_smiles as _canonicalize_smiles
    from ..core.cache import cache_get as _cache_get, cache_set as _cache_set
    from ..core.rate_limit import (
        structure_enter as _structure_enter,
        structure_exit as _structure_exit,
    )

    offset = (page - 1) * page_size
    cache_key = (f"v2:unified-search:{mode}:{round(threshold, 3)}"
                 f":{page}:{page_size}:{query}")
    held: list[str] | None = None  # 结构检索闸门句柄(exact 模式不取)
    canonical: Any = None
    chemicals: list[dict[str, Any]] = []
    total: int | None = None
    reactions: list[dict[str, Any]] = []
    cas_fetch_pending = False
    cas_fetch_hit_id: int | None = None
    has_more = False
    capped = False
    try:
        if mode != "exact":
            cached = await _cache_get(cache_key)
            if cached:
                return cached
            held = await _structure_enter(actor_id)
        # RDKit 解析/canonical 化是 CPU 计算, 丢线程池避免卡事件循环
        # (0915 裁定; 同款先例=resolve_or_create 的 chemical_properties)。
        canonical = await _asyncio.to_thread(_canonicalize_smiles, query)
        (chemicals, total, reactions, cas_fetch_pending, canonical,
         cas_fetch_hit_id, has_more, capped) = await run_search_query(
            db, query, mode, canonical, page, page_size, offset,
            actor_id=actor_id, threshold=threshold,
        )
        data: dict[str, Any] = {
            "query": query, "mode": mode, "canonical_smiles": canonical,
            "threshold": threshold,
            "page": page, "page_size": page_size, "total": total,
            # has_more 收口(0914 #2): page 已达契约上限(le=20)时无合法 page+1,
            # has_more 必须 False — 否则 Web(页面 clamp 回 20)形成第 20 页自循环。
            "has_more": has_more and page < 20,
            # capped(0915): substructure snapshot 达到产品上限 250 时 True。
            # 语义: 达到产品返回上限, 数据库真实总匹配数未知 — total 不得被
            # 消费方当成数据库真实总数。
            "capped": capped,
            "chemicals": chemicals, "reactions": reactions,
        }
        if cas_fetch_pending:
            data["cas_fetch_pending"] = True  # 前端提示: 正在获取该CAS数据
        if cas_fetch_hit_id:
            # 0902 P3b: 同步拉命中 — 数据已落库, 前端直接跳详情页
            data["cas_fetch_chemical_id"] = cas_fetch_hit_id
        if mode != "exact":
            await _cache_set(cache_key, data, ttl=300)
        return data
    finally:
        await _structure_exit(held)


async def run_search_query(
    db: Any, query: str, mode: str, canonical: Any, page: int, page_size: int,
    offset: int,
    *, actor_id: int | None = None, threshold: float = 0.7,
) -> tuple[list[dict[str, Any]], int | None, list[dict[str, Any]], bool, Any, int | None, bool, bool]:
    """执行搜索主体(化合物命中/total/反应/cas_fetch_pending/canonical 回写)。

    返回 8 元组:
        (chemicals, total, reactions, cas_fetch_pending, canonical,
         cas_fetch_hit_id, has_more, capped)
    canonical 可能被 substructure 分支重新赋值(bounded), 调用方需取回。
    capped(0915): 仅 substructure 模式可能为 True — snapshot 达到产品上限
    SUBSTRUCTURE_SNAPSHOT_CAP(250)。语义: "达到产品返回上限; 数据库真实总匹配
    数未知", 消费方(UI/Agent)不得把 total 冒充数据库真实总数。
    has_more 按 mode:
        exact 名称路径 = run_name_search 候选窗口(权威翻页字段);
        exact strong-identity(clauses) = exact total/page 推导;
        substructure/similarity = 本轮前语义(total!=None 按 total/page,
        total=None 当前页满则可能还有);
        其余 False。
    actor_id: 鉴权用户 id(匿名=None) — 仅用于 CAS-miss 入队限流身份。
    threshold: similarity 模式阈值(0.4-1.0, 默认 0.7)。similarity 唯一入口
        是本 search 端点(/chemicals/{id}/similarity 已随 20dfdbc 剥离)。
    """
    chemicals: list[dict[str, Any]] = []
    total: int | None = None
    cas_fetch_pending = False
    cas_fetch_hit_id: int | None = None  # 0902 P3b: 同步拉命中, 前端直跳详情页
    capped = False  # 0915: substructure snapshot 达到产品上限(250)
    clauses: list[str] = []
    params: dict[str, Any] = {}
    try:
        if mode == "exact":
            await db.execute(text("SET LOCAL statement_timeout = '5s'"))
        if mode == "substructure":
            if not canonical:
                raise SearchError(INVALID_STRUCTURE, "无法识别该 SMILES 结构")
            canonical = bounded_substructure_smiles(canonical)
            # P0(0912): 有上限 GiST snapshot + Redis(同 chemicals.substructure_page) —
            # 无序 GiST 必被 planner 选中, 深页不再重扫候选集, TTL 内分页确定。
            from .chemicals import (SUBSTRUCTURE_SNAPSHOT_CAP, hydrate_chemicals,
                                    substructure_snapshot)
            from .chemicals import _snapshot_total
            ids = await substructure_snapshot(db, canonical)
            total = _snapshot_total(ids, offset, page_size)
            capped = len(ids) >= SUBSTRUCTURE_SNAPSHOT_CAP
            chemicals = await hydrate_chemicals(db, ids[offset:offset + page_size])
        elif mode == "similarity":
            if not canonical:
                raise SearchError(INVALID_STRUCTURE, "无法识别该 SMILES 结构")
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
            # KNN GiST 保持; threshold 后过滤 + Python 侧分页(同 similarity_page)。
            window = offset + page_size
            chemicals = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT},
                       1 - (c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles)))
                FROM chemistry.chemicals c
                WHERE c.mol IS NOT NULL
                ORDER BY c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles))
                LIMIT :window
            """, {"smiles": canonical, "window": window})
            qualifying = [item for item in chemicals if (item.get("similarity") or 0) >= threshold]
            qualifying.sort(key=lambda item: item.get("similarity") or 0, reverse=True)
            # total 语义(0912): prefix 内已跌破 threshold/prefix 未满 ⇒ 精确总数;
            # 否则 None("更多结果")。禁止用本页条数冒充总数。
            # cut_inside ⇒ qualifying 已含全部合格项(检索无 SQL 偏移, 从第 1 条
            # 起的前缀) ⇒ 精确 total = len(qualifying), 与页码无关。
            cut_inside = len(chemicals) < window or bool(
                chemicals and (chemicals[-1].get("similarity") or 0) < threshold)
            total = len(qualifying) if cut_inside else None
            chemicals = qualifying[offset:offset + page_size]
        else:
            clauses = []
            params = {"q": query, "uq": query.upper(), "limit": page_size, "offset": offset}
            name_has_more = False
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
                    # 0904 敞口收口: 分支注释宣称限流但无 enforce 调用(匿名可
                    # 无限建占位行+触发外部链)。按注释原口径补齐: 鉴权用户
                    # 10/min/actor; 匿名(BFF/SSR=loopback, 无真实IP)共享全局桶
                    # 30/min。超限/限速服务异常一律降级为不入队(state=miss),
                    # 绝不阻塞搜索响应(注释原语义); 只挡占行+入队副作用面。
                    rate_state = "ok"
                    try:
                        from ..core.rate_limit import enforce as _enforce_cas
                        from ..core.rate_limit import RateLimitError as _RateLimitError
                        if actor_id is not None:
                            await _enforce_cas("cas-search-fetch", str(actor_id), 10, 60)
                        else:
                            await _enforce_cas("cas-search-fetch", "anonymous-global", 30, 60)
                    except _RateLimitError:
                        # G2.R: 只降级限流语义异常(超限/限流不可用→不入队)。
                        # 该 try 块仅含 enforce 调用, 无业务副作用需要兜底。
                        rate_state = "miss"
                    try:
                        from .cb import (
                            cas_search_state, enqueue_cas_search_fetch,
                        )
                        # rate 拒绝时跳过 state 询问, state 保持 "miss" 之外的
                        # 平价值: 只是不入队, 不对 CB 收录下任何结论(与
                        # cas_search_state 的 miss=终态负缓存语义区分)。
                        state = "throttled" if rate_state == "miss" else await cas_search_state(db, query)
                        if state == "new":
                            # Search System Governance(2026-09-13): CAS miss 保持
                            # 受控入队(rate/dedupe/governance 原样), 但响应不再
                            # 同步等待外部 CB fetch —— sync_fetch_and_store 的 3s
                            # 预算从 critical path 移除, 由后台 worker 消化队列。
                            # 0907 门禁不变: resolver 裁定穿透, chemical_id 非空
                            # 才占行; None(AMBIGUOUS/CONFLICT)不落任何候选行。
                            enqueued, _res_status, _row_id = await enqueue_cas_search_fetch(
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
            # 本次响应即返回该行. 结构行与反应创建同形态, 延伸字段留 PB/CB 自然演进.
            # 建行失败降级为空结果, 不阻塞.
            # 副作用闸门(0914 #5): 建行=写 chemistry.chemicals + discovery 入队,
            # 与 CAS miss 同口径限流(鉴权 10/min/actor, 匿名共享 30/min);
            # 超限/限速服务异常降级为不建行(返回空结果), 不阻塞搜索响应。
            if not chemicals and page == 1 and canonical and len(query) <= 4000:
                from ..core.rate_limit import RateLimitError as _RateLimitError
                _rate_limited = False
                try:
                    if actor_id is not None:
                        await enforce("smiles-create", str(actor_id), 10, 60)
                    else:
                        await enforce("smiles-create", "anonymous-global", 30, 60)
                except _RateLimitError:
                    # G2.R: 限流语义异常显式降级为不建行(原 except Exception 语义)。
                    _rate_limited = True
                if not _rate_limited:
                    try:
                        from .reactions import UnresolvedIdentityError, resolve_or_create_chemical
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
                    except UnresolvedIdentityError:
                        # E9-B fail-closed: CONFLICT/AMBIGUOUS → 不建行、零副作用,
                        # 搜索本身正常返回"未创建/无命中"语义(不 500)。
                        await db.rollback()
                    except Exception:
                        await db.rollback()  # 建行失败不阻塞搜索响应(业务容错保持)
            if not chemicals and not canonical and name_query_width(query) >= MIN_FUZZY_NAME_LENGTH:
                # Search System Governance(2026-09-13): 名称查询走统一候选服务
                # run_name_search —— exact 短路(preferred>iupac>name_index 等值,
                # benzoic acid 本体先于 substring 命中), exact 全 miss 才 fuzzy,
                # fuzzy substring 仅当 normalize 后 >=3 字符(A甲/甲A/甲醇 exact-only),
                # 三来源统一候选流分页(无 per-tier OFFSET / 无 offset==0 闸门),
                # has_more 来自同一窗口(offset+page_size+1), 名称面零 count SQL。
                chemicals, name_has_more = await run_name_search(
                    db, query, page_size, offset,
                )
            elif not chemicals and not canonical and name_query_width(query) < MIN_FUZZY_NAME_LENGTH:
                raise SearchError(QUERY_TOO_SHORT, "名称查询至少需要 3 个字符（中文至少 2 个字）")
            # 搜索命中卡片 → 同时查 zh 记录态和时间(准线§1 统一触发, 2026-08-30):
            # 命中行六态判定, enqueue 态真实入列(超窗刷新/超窗重问/error)。
            # 首问/负缓存内不动作。命中多行只判第一页首行(卡片=代表行)。
            if (
                chemicals and page == 1 and CAS_RE.fullmatch(query)
            ):
                try:
                    from .cb import cb_decide, enqueue_cas_job
                    hit_id = chemicals[0]["id"]
                    decision = await cb_decide(db, hit_id)
                    if decision.startswith("enqueue") and decision != "enqueue_first":
                        await enqueue_cas_job(
                            db, chemical_id=hit_id, cas_number=query,
                            priority=40, request_context={"reason": "search_stale"},
                        )
                        await db.commit()
                except Exception:
                    await db.rollback()  # 判定/入列失败不阻塞搜索响应

        try:
            if mode == "exact" and not canonical and name_query_width(query) >= MIN_FUZZY_NAME_LENGTH:
                if clauses:
                    # strong-identity exact: 唯一允许保留 exact total 的路径
                    # (与召回同 clause, 实测 count 1-6ms)。
                    total = (await db.execute(text(f"""
                        SELECT count(*) FROM chemistry.chemicals c
                        WHERE {' OR '.join(clauses)}
                    """), params)).scalar()
                # 名称路径: 彻底删除 fuzzy/name exact 的 count(*)(Search System
                # Governance 2026-09-13) —— total 保持 None, has_more 由
                # run_name_search 的同一候选窗口给出, 不允许第二条 count SQL。
        except Exception:
            total = None

        reactions = await reaction_lookup(
            db, query, page_size, actor_id=actor_id
        ) if mode == "exact" and page == 1 else []
        # 0902 P2: 身份键唯一命中直达 — 无歧义身份键(CAS/InChIKey/canonical SMILES/
        # 显式 id:/cid: 前缀)且恰 1 行化合物 0 反应 → 前端/API 跳详情页。
        # 纯数字无前缀不直达: hcid/cid/hrid 三路天然歧义(格式不可控, 用户裁定)。
        if (
            mode == "exact" and page == 1
            and len(chemicals) == 1 and not reactions
        ):
            _pfx, _s, _val = query.partition(":")
            _pfx = _pfx.strip().lower()
            unambiguous = bool(
                CAS_RE.fullmatch(query)
                or INCHIKEY_RE.fullmatch(query.upper())
                or canonical
                or (_s and _pfx in ("id", "cid") and _val.strip().isdigit())
            )
            if unambiguous:
                cas_fetch_hit_id = chemicals[0]["id"]
    except SearchError:
        raise
    # G2.3D: chemicals 查询内核 neutral 异常 → 语义 kind, detail 原文
    # (c30dfe8 基线契约恢复; 禁止落入下方 generic 兜底被覆盖)。
    except InvalidSmilesError as exc:
        raise SearchError(INVALID_STRUCTURE, str(exc)) from exc
    except SubstructureTooSmallError as exc:
        raise SearchError(SUBSTRUCTURE_TOO_SMALL, str(exc)) from exc
    except InvalidDoiError as exc:
        raise SearchError(INVALID_DOI, str(exc)) from exc
    except SubstructureUnavailableError as exc:
        # snapshot 层已 rollback(statement-timeout 分支)或无未决写;
        # slow-window 分支无 DB 状态变化, 不再重复 rollback。
        raise SearchError(BACKEND_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        raise SearchError(BACKEND_UNAVAILABLE, "查询超时，请使用更精确的名称、标识符或结构") from exc
    # has_more 按 mode 收口(correction 2026-09-13): name_has_more 不得作为
    # 全 mode 兜底 —— substructure/similarity 保留本轮前的分页语义。
    if mode == "exact":
        if clauses and total is not None:
            # strong-identity exact: exact total 契约保留, has_more 由 total/page 推导
            has_more = (page * page_size) < total
        else:
            # 名称路径: name_has_more 来自 run_name_search 候选窗口(权威)
            has_more = name_has_more
    elif mode in ("substructure", "similarity"):
        # structure search 算法/snapshot/threshold/total 定义不动;
        # has_more 恢复本轮前的推导语义:
        #   total != None → page*page_size < total
        #   total is None → 当前页满则可能还有(保守继续入口)
        if total is not None:
            has_more = (page * page_size) < total
        else:
            has_more = len(chemicals) == page_size
    else:
        has_more = False
    return chemicals, total, reactions, cas_fetch_pending, canonical, cas_fetch_hit_id, has_more, capped
