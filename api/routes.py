"""Public read API for the autonomous chemicals and reactions data model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text

from .core.cache import cache_get, cache_set
from .core.database import get_db
from .core.security import Actor, public_or_actor
from .services.reactions import load_reaction_detail
from .services.search import (
    INVALID_DOI, INVALID_STRUCTURE, SUBSTRUCTURE_TOO_SMALL,
    QUERY_TOO_SHORT, BACKEND_UNAVAILABLE,
    SearchError, execute_search,
)
from .rate_limit_http import to_http_exception  # noqa: E402  (G2.R HTTP bridge)
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
    normalize_enrich,
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
    locale: str | None = Query(None),  # 白名单归一在 service(normalize_cb_locale): 未指定/非法 → en
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    # G2.4B: 编排下沉 services/chemicals.get_chemical_detail; adapter 只保留
    # 参数解析/auth/priority policy/display 投影/404 映射。
    # E9-B 1.1: 唯一公开 detail 能力。enrich=core(零 provider) /
    # full(semantic detail, 内部调 services/enrichment + services/cb)。
    # locale(2026-10): CB 行选择上下文, 白名单校验, 未传 → service 默认 en。
    try:
        result = await get_chemical_detail(
            db, chemical_id,
            actor_id=actor.id if actor else None,
            # 优先级对齐 CB 定论: 80=用户(登录) / 50=后台. 匿名 SSR(爬虫翻页)
            # 不是用户, 不占用户位(2026-08-27 血案: 匿名流量曾以 80 插队灌队列).
            priority=80 if actor is not None else 50,
            enrich=normalize_enrich(enrich),
            locale=locale,
        )
    except ChemicalNotFoundError as exc:
        raise HTTPException(404, "化合物不存在") from exc
    return result


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
