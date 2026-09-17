"""Molecule/reaction rendering — HTTP adapter (G2.2).

领域 lookup/render 在 api/services/rendering.py(transport-neutral, 唯一一份);
本文件只保留: path/query 解析、dependency、Cache-Control、media_type、
HTTPException 映射。行为(URL/auth/status/cache/响应)与基线逐字一致。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from .core.database import get_db
from .core.security import Actor, public_or_actor
from .services import rendering as render_service

router = APIRouter(tags=["molecule"])


@router.get("/mol/{chemical_id}/svg", operation_id="render_molecule_svg")
async def render_molecule(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    w: int = 400,
    h: int = 300,
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    """Render a chemical structure to SVG by HCID.

    Caching is handled entirely by Cloudflare (immutable) — no Redis layer
    to avoid write-only keys from crawler traffic hitting unique URLs.
    """
    w = min(max(w, 50), 800)
    h = min(max(h, 50), 800)

    smiles = await render_service.lookup_molecule_smiles(db, chemical_id)
    if smiles is None:
        raise HTTPException(status_code=404, detail="化合物没有可渲染的结构表达")

    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    svg = await asyncio.to_thread(render_service.smiles_to_svg, smiles, w, h)
    if svg is None:
        raise HTTPException(status_code=400, detail="Invalid SMILES")

    return Response(content=svg, media_type="image/svg+xml", headers=headers)


@router.get("/mol/{chemical_id}/png")
async def render_molecule_png(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    w: int = 500,
    h: int = 375,
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    """Render a chemical structure to PNG by HCID (share-card image).

    Same semantics and caching policy as the SVG endpoint; PNG because
    social platforms do not accept SVG as og:image.
    """
    w = min(max(w, 50), 1200)
    h = min(max(h, 50), 1200)

    smiles = await render_service.lookup_molecule_smiles(db, chemical_id)
    if smiles is None:
        raise HTTPException(status_code=404, detail="化合物没有可渲染的结构表达")

    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    png = await asyncio.to_thread(render_service.smiles_to_png, smiles, w, h)
    if png is None:
        raise HTTPException(status_code=400, detail="Invalid SMILES")

    return Response(content=png, media_type="image/png", headers=headers)


@router.get("/reactions/{reaction_id}/svg", operation_id="render_reaction_svg")
async def render_reaction(
    reaction_id: int = Path(..., ge=1, le=2_147_483_647),
    w: int = 1200,
    h: int = 300,
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    """Render the stored reaction expression by stable reaction ID.

    Caching is handled entirely by Cloudflare — no Redis
    layer to avoid write-only keys from crawler traffic hitting unique URLs.

    shared-cache eligibility = visibility public AND moderation visible
    (不基于 actor 身份: public+visible 即使 owner/admin 请求, 匿名同样
    有权访问; public+hidden 即使 owner/admin 有权读取, 也不可 shared-
    cache)。TTL 5min 短窗接受最终一致性: 转私/隐藏/删除后旧 SVG 最多
    继续存在约 5 分钟。
    """
    w = min(max(w, 600), 1800)
    h = min(max(h, 180), 600)
    source = await render_service.lookup_reaction_render_source(
        db, reaction_id,
        viewer_id=actor.id if actor else 0,
        is_admin=bool(actor and actor.role == "admin"))
    if source is None:
        raise HTTPException(status_code=404, detail="反应没有可渲染的结构表达")

    svg = await asyncio.to_thread(render_service.reaction_to_svg,
                                  source.reaction_smiles, w, h)
    if svg is None:
        raise HTTPException(status_code=422, detail="反应结构无法渲染")
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control":
                 "public, max-age=300"
                 if source.is_public_visible
                 else "private, no-store"},
    )
