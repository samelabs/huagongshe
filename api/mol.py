"""Molecule SVG rendering using RDKit."""
import re
from rdkit import Chem
from rdkit.Chem import Draw, AllChem
from fastapi import APIRouter, HTTPException, Response
from .cache import cache_get, cache_set

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


@router.get("/mol/svg")
async def render_molecule(smiles: str, w: int = 400, h: int = 300):
    """Render a SMILES to SVG image. Cached in Redis."""
    w = min(max(w, 50), 800)
    h = min(max(h, 50), 800)

    cache_key = f"mol_svg:{smiles}:{w}x{h}"
    cached = await cache_get(cache_key)
    if cached:
        return Response(content=cached, media_type="image/svg+xml")

    svg = smiles_to_svg(smiles, w, h)
    if svg is None:
        raise HTTPException(status_code=400, detail="Invalid SMILES")

    await cache_set(cache_key, svg, ttl=86400)  # Cache 24h
    return Response(content=svg, media_type="image/svg+xml")
