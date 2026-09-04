"""Public read API for the autonomous chemicals and reactions data model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import text

from .core.cache import cache_get, cache_set
from .chemistry import canonicalize_smiles
from .core.database import get_db
from .enrichment import enqueue_chemical_if_needed
from .services.enrichment import display_details
from .core.security import Actor, internal_or_actor
from .services.reactions import load_reaction_detail
from .services.search import run_search_query
from .services.chemicals import (
    CHEMICAL_SELECT,
    fetch_chemicals, reaction_summaries,
    load_stats, load_public_config, load_datasets, load_sitemap_reactions,
    load_synonyms_page, substructure_page, similarity_page, fill_detail_context,
)

router = APIRouter(tags=["chemistry"])



@router.get("/stats")
async def stats(actor: Actor | None = Depends(internal_or_actor), db=Depends(get_db)):
    cached = await cache_get("v1:stats:exact")
    if cached:
        return cached
    data = await load_stats(db)
    await cache_set("v1:stats:exact", data, ttl=3600)
    return data


@router.get("/config")
async def public_config(actor: Actor | None = Depends(internal_or_actor), db=Depends(get_db)):
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
    try:
        chemicals, total, reactions, cas_fetch_pending, canonical, cas_fetch_hit_id = await run_search_query(
            db, query, mode, canonical, page, page_size, offset,
            actor_id=actor.id if actor else None,
        )
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
    if cas_fetch_hit_id:
        # 0902 P3b: 同步拉命中 — 数据已落库, 前端直接跳详情页
        data["cas_fetch_chemical_id"] = cas_fetch_hit_id
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
    await fill_detail_context(db, result, chemical_id, actor.id if actor else 0)
    details, job_id, needs_refresh = await enqueue_chemical_if_needed(
        db,
        chemical_id,
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
    from .services.cb import ensure_externals, sync_fetch_and_store

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
        # 首访: 同步拉取(3s 预算); 失败入队,本响应出空
        sync = await sync_fetch_and_store(db, chemical_id=chemical_id, cas_number=cas_number)
        if sync and sync["status"] == "ok":
            outcome = await ensure_externals(db, chemical_id, cas_number=cas_number)
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
    actor: Actor | None = Depends(internal_or_actor),
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

    total, items = await substructure_page(db, chemical_id, page, page_size)
    if total == -1:
        raise HTTPException(404, "化合物没有可检索结构")
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

    items = await similarity_page(db, chemical_id, threshold, page, page_size)
    if items is None:
        raise HTTPException(404, "化合物没有可检索结构")
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
    data = await load_reaction_detail(db, reaction_id, viewer_id, viewer_is_admin)
    if data is None:
        raise HTTPException(404, "反应不存在")
    return data


@router.get("/datasets")
async def datasets(
    actor: Actor | None = Depends(internal_or_actor),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(20, ge=1, le=50), db=Depends(get_db)
):
    return await load_datasets(db, page, page_size)


@router.get("/sitemap/reactions")
async def sitemap_reactions(
    actor: Actor | None = Depends(internal_or_actor),
    after_id: int = Query(0, ge=0), limit: int = Query(50000, ge=1, le=50000), db=Depends(get_db)
):
    """Keyset-paginated public reaction IDs for sitemap generation."""
    return await load_sitemap_reactions(db, after_id, limit)
