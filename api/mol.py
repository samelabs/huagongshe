"""Molecule and reaction SVG rendering using RDKit."""

from __future__ import annotations

import asyncio
import re
from rdkit import Chem
from rdkit.Chem import Draw, AllChem, rdChemReactions
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from .cache import cache_get, cache_set
from .database import get_db
from .security import Actor, optional_actor

router = APIRouter(tags=["molecule"])


def smiles_to_svg(smiles: str, width: int = 400, height: int = 300) -> str:
    """Render a SMILES string to an SVG string."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    AllChem.Compute2DCoords(mol)
    drawer = Draw.rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = drawer.drawOptions()
    opts.bondLineWidth = 2
    opts.scaleBondWidth = False
    opts.padding = 0.12
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    svg = re.sub(r'<\?xml[^>]+\?>', '', svg)
    return svg


def reaction_to_svg(reaction_smiles: str, width: int = 1200, height: int = 300) -> str | None:
    """Render a reaction SMILES as a clean, atom-map-free SVG equation."""
    if not reaction_smiles or len(reaction_smiles) > 20000:
        return None
    try:
        reaction = rdChemReactions.ReactionFromSmarts(reaction_smiles, useSmiles=True)
        if reaction is None or not reaction.GetNumReactantTemplates() or not reaction.GetNumProductTemplates():
            return None
        for molecule in (
            list(reaction.GetReactants())
            + list(reaction.GetAgents())
            + list(reaction.GetProducts())
        ):
            for atom in molecule.GetAtoms():
                atom.SetAtomMapNum(0)
        drawer = Draw.rdMolDraw2D.MolDraw2DSVG(width, height)
        options = drawer.drawOptions()
        options.bondLineWidth = 1.8
        options.scaleBondWidth = False
        options.padding = 0.08
        drawer.DrawReaction(reaction)
        drawer.FinishDrawing()
        return re.sub(r'<\?xml[^>]+\?>', '', drawer.GetDrawingText())
    except Exception:
        return None


@router.get("/mol/svg")
async def render_molecule(
    smiles: str = Query(..., min_length=1, max_length=4000),
    w: int = 400,
    h: int = 300,
):
    """Render a SMILES to SVG image. Cached in Redis."""
    w = min(max(w, 50), 800)
    h = min(max(h, 50), 800)

    cache_key = f"mol_svg:{smiles}:{w}x{h}"
    cached = await cache_get(cache_key)
    if cached:
        return Response(content=cached, media_type="image/svg+xml")

    svg = await asyncio.to_thread(smiles_to_svg, smiles, w, h)
    if svg is None:
        raise HTTPException(status_code=400, detail="Invalid SMILES")

    await cache_set(cache_key, svg, ttl=86400)  # Cache 24h
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/reactions/{reaction_id}/svg")
async def render_reaction(
    reaction_id: int,
    w: int = 1200,
    h: int = 300,
    actor: Actor | None = Depends(optional_actor),
    db=Depends(get_db),
):
    """Render the stored reaction expression by stable reaction ID."""
    w = min(max(w, 600), 1800)
    h = min(max(h, 180), 600)
    row = (await db.execute(text("""
        SELECT reaction_smiles,updated_at,visibility
        FROM chemistry.reactions
        WHERE id=:id AND reaction_smiles IS NOT NULL
          AND (:is_admin OR created_by_user_id=:viewer_id
               OR (visibility='public' AND moderation_status='visible'))
    """), {
        "id": reaction_id, "viewer_id": actor.id if actor else 0,
        "is_admin": bool(actor and actor.role == "admin"),
    })).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="反应没有可渲染的结构表达")

    version = int(row[1].timestamp()) if row[1] else 0
    cache_key = f"reaction_svg:v1:{reaction_id}:{version}:{w}x{h}"
    cached = await cache_get(cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400" if row[2] == "public" else "private, no-store"},
        )

    svg = await asyncio.to_thread(reaction_to_svg, row[0], w, h)
    if svg is None:
        raise HTTPException(status_code=422, detail="反应结构无法渲染")
    await cache_set(cache_key, svg, ttl=86400)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400" if row[2] == "public" else "private, no-store"},
    )
