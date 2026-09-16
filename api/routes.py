"""Public read API for the autonomous chemicals and reactions data model."""

from __future__ import annotations
import asyncio

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import text

from .core.cache import cache_get, cache_set
from .chemistry import canonicalize_smiles
from .core.database import get_db
from .enrichment import enqueue_chemical_if_needed
from .services.enrichment import display_details
from .core.security import Actor, public_or_actor
from .services.reactions import load_reaction_detail
from .services.search import run_search_query
from .services.chemicals import (
    CHEMICAL_SELECT,
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
    cas_fetch_pending = False  # CAS miss 已入队CB获取(standalone任务)
    # 结构检索登录墙(2026-08-26): GIST 单路 ~400ms 但并发无上限, 爬虫 12 路并发
    # 曾把机器打进 swap 全站僵死. exact 保持匿名(SSR); 结构模式需已鉴权 actor.
    if mode != "exact" and actor is None:
        raise HTTPException(401, "结构检索（子结构/相似度）需要登录或提供 API Token")
    offset = (page - 1) * page_size
    held: list[str] | None = None  # 结构检索闸门句柄(exact 模式不取)
    cache_key = f"v2:unified-search:{mode}:{round(threshold,3)}:{page}:{page_size}:{query}"
    # 0914 #6: threshold 超 3 位小数时 round 进缓存键会同键不同结果(TTL 300s
    # 内串页), 显式 422 — 契约即 3 位(0.400–1.000), 而非静默吸附。
    if mode == "similarity" and round(threshold, 3) != threshold:
        raise HTTPException(422, "threshold 仅支持 3 位小数 (0.400–1.000)")
    if mode != "exact":
        cached = await cache_get(cache_key)
        if cached:
            return cached
        # 结构检索资源闸门(0912): cache miss 才进入。两层 —
        # ① fixed-window 限频(actor 6/min + global 30/min)
        # ② in-flight 租约(actor 2 + global 4) — 依据 pool 5+5=10 连接 /
        # similarity 冷查 ~5s / statement_timeout 8s: 最坏 4 个昂贵结构查询
        # 同时占连接, 至少 6 个留给普通请求。超限立即 429, 不占连接等 503。
        held = await structure_enter(actor.id if actor is not None else None)
    # Exact searches can include user-created reactions. Keep them live so a
    # create, edit or delete is reflected immediately. Only expensive
    # structure searches use the short-lived shared cache.

    # RDKit 解析/canonical 化是 CPU 计算, 丢线程池避免卡事件循环
    # (0915 裁定; 同款先例=resolve_or_create 的 chemical_properties)。
    canonical = await asyncio.to_thread(canonicalize_smiles, query)
    try:
        (chemicals, total, reactions, cas_fetch_pending, canonical,
         cas_fetch_hit_id, has_more, capped) = await run_search_query(
            db, query, mode, canonical, page, page_size, offset,
            actor_id=actor.id if actor else None, threshold=threshold,
        )
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, "查询超时，请使用更精确的名称、标识符或结构") from exc
    finally:
        await structure_exit(held)

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
        await cache_set(cache_key, data, ttl=300)
    return data


from .core.rate_limit import enforce, structure_enter, structure_exit  # noqa: E402  (结构检索闸门 0912 + externals 限流)


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
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    rows = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c WHERE c.id=:id
    """, {"id": chemical_id})
    if not rows:
        raise HTTPException(404, "化合物不存在")
    result = rows[0]
    await fill_detail_context(db, result, chemical_id, actor.id if actor else 0)
    details, job_id, needs_refresh = await enqueue_chemical_if_needed(
        db,
        chemical_id,
        # 优先级对齐 CB 定论: 80=用户(登录) / 50=后台. 匿名 SSR(爬虫翻页)
        # 不是用户, 不占用户位(2026-08-27 血案: 匿名流量曾以 80 插队灌队列).
        priority=80 if actor is not None else 50,
        # H1: 详情页读驱动回补 = 产品 use-case policy, 匿名/登录一律允许。
        allow_refresh=True,
        actor=actor,
        request=request,
    )
    if job_id is not None:
        await db.commit()
    result["details"] = display_details(details) if display else details
    result["enrichment"] = {
        "status": "queued" if job_id is not None else ("stale" if needs_refresh else "current"),
        "job_id": job_id,
    }
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
            await enforce("externals-fetch", str(actor.id), 10, 60)
        else:
            await enforce("externals-fetch", "anonymous-global", 30, 60)
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
