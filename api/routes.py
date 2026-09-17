"""Public read API for the autonomous chemicals and reactions data model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import text

from .core.cache import cache_get, cache_set
from .core.database import get_db
from .services.enrichment import display_details
from .core.security import Actor, public_or_actor
from .services.reactions import load_reaction_detail
from .services.search import (
    INVALID_DOI, INVALID_STRUCTURE, SUBSTRUCTURE_TOO_SMALL,
    QUERY_TOO_SHORT, BACKEND_UNAVAILABLE,
    SearchError, execute_search,
)
from .rate_limit_http import enforce_http, to_http_exception  # noqa: E402  (externals 限流; G2.R HTTP bridge)
from .core.rate_limit import RateLimitError  # noqa: E402

# service 语义类别 → 基线 HTTP status 唯一映射(G2.3 final; detail 逐字不变)
_STATUS_BY_KIND = {
    INVALID_STRUCTURE: 400,
    SUBSTRUCTURE_TOO_SMALL: 422,
    INVALID_DOI: 400,
    QUERY_TOO_SHORT: 422,
    BACKEND_UNAVAILABLE: 503,
}
from .services.chemicals import (
    CHEMICAL_SELECT,
    ChemicalNotFoundError, get_chemical_detail,
    fetch_chemicals, reaction_summaries,
    load_public_config, load_datasets, load_sitemap_reactions,
    load_synonyms_page, fill_detail_context,
)

router = APIRouter(tags=["chemistry"])



@router.get("/config")
async def public_config(actor: Actor | None = Depends(public_or_actor), db=Depends(get_db)):
    """公开系统配置，供前端 layout 动态渲染。"""
    cache_key = "config:public:all"
    cached = await cache_get(cache_key)
    if cached:
        return cached
    result = await load_public_config(db)
    await cache_set(cache_key, result, ttl=300)
    return result


@router.get(
    "/search",
    operation_id="search_chemistry_data",
    summary="统一查询化合物和反应",
)
async def search(
    actor: Actor | None = Depends(public_or_actor),
    q: str = Query(..., min_length=1, max_length=4000),
    mode: str = Query("exact", pattern="^(exact|substructure|similarity)$"),
    threshold: float = Query(0.7, ge=0.4, le=1.0),
    # threshold 契约限定 3 位小数(0914 #6): 缓存键与过滤值必须同一口径,
    # 否则 round(t,3) 同键不同结果(TTL 300s 内串页)。URI 传 0.70004 → 422。
    page: int = Query(1, ge=1, le=20),
    page_size: int = Query(30, ge=1, le=100),
    db=Depends(get_db),
):
    """One entry point for names, external identifiers, SMILES and structures."""
    query = q.strip()
    # 结构检索登录墙(2026-08-26): GIST 单路 ~400ms 但并发无上限, 爬虫 12 路并发
    # 曾把机器打进 swap 全站僵死. exact 保持匿名(SSR); 结构模式需已鉴权 actor.
    if mode != "exact" and actor is None:
        raise HTTPException(401, "结构检索（子结构/相似度）需要登录或提供 API Token")
    # 0914 #6: threshold 超 3 位小数时 round 进缓存键会同键不同结果(TTL 300s
    # 内串页), 显式 422 — 契约即 3 位(0.400–1.000), 而非静默吸附。
    if mode == "similarity" and round(threshold, 3) != threshold:
        raise HTTPException(422, "threshold 仅支持 3 位小数 (0.400–1.000)")
    try:
        return await execute_search(
            db, query, mode, threshold=threshold, page=page,
            page_size=page_size,
            actor_id=actor.id if actor else None,
        )
    except SearchError as exc:  # service 领域错误 → 原基线 status/detail
        raise HTTPException(_STATUS_BY_KIND[exc.kind], exc.detail) from exc
    except RateLimitError as exc:  # G2.R neutral 闸门异常 → HTTP bridge
        raise to_http_exception(exc) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, "查询超时，请使用更精确的名称、标识符或结构") from exc






@router.get(
    "/chemicals/{chemical_id}",
    operation_id="get_chemical",
    summary="读取一个化合物记录",
)
async def chemical_detail(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    enrich: str = Query("core", pattern="^(core|full)$"),
    display: bool = Query(False),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    # G2.4B: 编排下沉 services/chemicals.get_chemical_detail; adapter 只保留
    # 参数解析/auth/priority policy/display 投影/404 映射。
    try:
        result = await get_chemical_detail(
            db, chemical_id,
            actor_id=actor.id if actor else None,
            # 优先级对齐 CB 定论: 80=用户(登录) / 50=后台. 匿名 SSR(爬虫翻页)
            # 不是用户, 不占用户位(2026-08-27 血案: 匿名流量曾以 80 插队灌队列).
            priority=80 if actor is not None else 50,
        )
    except ChemicalNotFoundError as exc:
        raise HTTPException(404, "化合物不存在") from exc
    result["details"] = display_details(result["details"]) if display else result["details"]
    return result


@router.get("/chemicals/{chemical_id}/externals", operation_id="get_chemical_externals",
            summary="化合物的中文扩展信息与供应商")
async def chemical_externals(
    request: Request,
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    """CB 扩展读端点: 读库+ensure 驱动(新 CAS 首访同步拉, 超期 worker 刷).

    遵循公开读口径: 无原站标识; 404 = 化合物不存在;
    entry/suppliers 为空 = 该化合物无 CAS 或源站无数据(非错误)。
    """
    from .services.cb import ensure_externals, negative_is_fresh, sync_fetch_and_store

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
    if outcome["state"] == "stale":
        # 六态判定需再问(超窗刷新/超窗重问/error): 出旧数据同时入列
        from .services.cb import enqueue_cas_job
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=cas_number, priority=40,
            request_context={"reason": "stale_refresh"},
        )
        await db.commit()
        outcome = {"state": "fresh", "entry": outcome.get("entry"),
                   "suppliers": outcome.get("suppliers") or [], "job_id": job_id}
    if outcome["state"] == "absent":
        # B-minimal: fresh cas_locator negative → 明确 not_found 在重问窗内,
        # 零同步 fetch 零 enqueue(此前每次页面访问=1次同步外呼+1次入列重抓)。
        # expired → 允许现有同步验证链继续。
        if await negative_is_fresh(db, "cas_locator", cas_number=cas_number):
            return {
                "chemical_id": chemical_id,
                "state": "fresh",
                "entry": None, "suppliers": [], "job_id": None,
                "negative": True,  # 内部 decision; 不扩前端公开 state 协议
            }
        # P1修复(II): 同步外呼限流只覆盖"即将发生同步上游外呼"的分支(照抄
        # smiles-create 口径) — 同步外呼有 3s 预算且全程持有 DB 连接(pool 仅
        # 5+5), 爬虫顺序扫 HCID 可打满连接池。额度不变: 10/min 鉴权、
        # 30/min 匿名全局。不得放 handler 入口: fresh cache/fresh DB/
        # fresh negative/stale enqueue/no_cas/404 这些零外呼路径不消耗配额,
        # Redis 故障时也不该把正常读取打成 503。
        if actor is not None:
            await enforce_http("externals-fetch", str(actor.id), 10, 60)
        else:
            await enforce_http("externals-fetch", "anonymous-global", 30, 60)
        # 首访: 同步拉取(3s 预算); 失败入队,本响应出空
        sync = await sync_fetch_and_store(db, chemical_id=chemical_id, cas_number=cas_number)
        if sync and sync["status"] == "ok":
            outcome = await ensure_externals(db, chemical_id, cas_number=cas_number)
        elif sync and sync["status"] == "not_found":
            # 明确 not_found: negative 已在 sync 内记录 — 不 enqueue
            # (二连击修复: 一次访问最多一次上游验证, 不再排队重抓)
            outcome = {"state": "fresh", "entry": None, "suppliers": [],
                       "job_id": None}
        else:
            from .services.cb import enqueue_cas_job
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
    actor: Actor | None = Depends(public_or_actor),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(100, ge=1, le=500),
    db=Depends(get_db),
):
    offset = (page - 1) * page_size
    total, values = await load_synonyms_page(db, chemical_id, offset, page_size)
    if total is None:
        raise HTTPException(404, "化合物不存在")
    return {
        "chemical_id": chemical_id,
        "total": total,
        "page": page,
        "page_size": page_size,
        "synonyms": list(values or []),
    }


@router.get("/chemicals/{chemical_id}/reactions")
async def chemical_reactions(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor | None = Depends(public_or_actor),
    role: str = Query("any", pattern="^(any|reactant|reagent|solvent|catalyst|product)$"),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    total, items = await reaction_summaries(db, [chemical_id], role, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "reactions": items}


@router.get(
    "/reactions/{reaction_id}",
    operation_id="get_reaction",
    summary="读取一个反应记录",
)
async def reaction_detail(
    reaction_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    viewer_id = actor.id if actor else 0
    viewer_is_admin = bool(actor and actor.role == "admin")
    data = await load_reaction_detail(db, reaction_id, viewer_id, viewer_is_admin)
    if data is None:
        raise HTTPException(404, "反应不存在")
    return data


@router.get("/datasets")
async def datasets(
    actor: Actor | None = Depends(public_or_actor),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(20, ge=1, le=50), db=Depends(get_db)
):
    return await load_datasets(db, page, page_size)


@router.get("/sitemap/reactions")
async def sitemap_reactions(
    actor: Actor | None = Depends(public_or_actor),
    after_id: int = Query(0, ge=0), limit: int = Query(50000, ge=1, le=50000), db=Depends(get_db)
):
    """Keyset-paginated public reaction IDs for sitemap generation."""
    return await load_sitemap_reactions(db, after_id, limit)
