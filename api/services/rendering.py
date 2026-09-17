"""Transport-neutral rendering services (G2.2) — molecule/reaction 渲染唯一 owner。

G1A 冻结结论的机械落实:
- molecule SVG/PNG = shared kernel + 独立 scenario(共享 lookup/preparation,
  独立 representation/MIME/consumer surface)
- reaction SVG = visibility-aware lookup + cache policy 独立于 molecule

本文件职责(唯一 owner):
- molecule lookup:            lookup_molecule_smiles
- reaction visibility lookup: lookup_reaction_render_source(领域事实:
  存在性/visibility/moderation/owner/admin 可达性/render source)
- RDKit render kernel:        smiles_to_svg / smiles_to_png / reaction_to_svg
  (自 api/mol.py 逐行搬运, 计算体零改动)

不职责(全部留 transport adapter):
- HTTP Cache-Control / media_type / HTTPException 映射
- MCP ToolError 映射 / MCP 资源闸门(_render_enter/_render_exit)
禁止导入 fastapi/mcp/Request/Response/HTTPException/ToolError。
viewer 事实只传最小必要字段(viewer_id/is_admin), 不引入带 transport
依赖的身份类型(§8: 不借 rendering slice 重构 security.py)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import AllChem, Draw, rdChemReactions
from sqlalchemy import text


# ---------------------------------------------------------------------------
# molecule lookup(唯一 owner; HTTP SVG/PNG 与 MCP 共用)
# ---------------------------------------------------------------------------

async def lookup_molecule_smiles(db, chemical_id: int) -> str | None:
    """按 HCID 取可渲染 SMILES; 无化合物或无可渲染表达 → None。

    消费方各自映射: HTTP→404「化合物没有可渲染的结构表达」;
    MCP→ToolError「化合物不存在或没有可渲染的结构表达」。
    """
    row = (await db.execute(text(
        "SELECT smiles FROM chemistry.chemicals WHERE id=:id"
    ), {"id": chemical_id})).fetchone()
    if not row or not row[0]:
        return None
    return row[0]


# ---------------------------------------------------------------------------
# reaction visibility-aware lookup(唯一 owner; HTTP 与 MCP 共用)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReactionRenderSource:
    """reaction render 的领域事实(transport-neutral)。

    visibility/moderation_status 是领域事实; is_public_visible 表达
    "reaction 当前公开可见"(public AND moderation visible, 不基于 actor)。
    Cache-Control/max-age/TTL 等 HTTP 策略不在 service —— 由 HTTP adapter
    依据本领域事实推导; MCP adapter 只消费 reaction_smiles。
    """

    reaction_smiles: str
    visibility: str
    moderation_status: str

    @property
    def is_public_visible(self) -> bool:
        return self.visibility == "public" and self.moderation_status == "visible"


async def lookup_reaction_render_source(
    db, reaction_id: int, *, viewer_id: int, is_admin: bool,
) -> ReactionRenderSource | None:
    """visibility-aware 查询: 不存在/无表达/不可见 → None。

    可达规则(admin OR owner OR public+visible)与基线 SQL 逐字一致;
    消费方各自映射: HTTP→404「反应没有可渲染的结构表达」;
    MCP→ToolError「反应不存在或没有可渲染的表达」。
    """
    row = (await db.execute(text("""
        SELECT reaction_smiles,updated_at,visibility,moderation_status
        FROM chemistry.reactions
        WHERE id=:id AND reaction_smiles IS NOT NULL
          AND (:is_admin OR created_by_user_id=:viewer_id
               OR (visibility='public' AND moderation_status='visible'))
    """), {
        "id": reaction_id, "viewer_id": viewer_id, "is_admin": is_admin,
    })).fetchone()
    if not row or not row[0]:
        return None
    return ReactionRenderSource(
        reaction_smiles=row[0], visibility=row[2], moderation_status=row[3])


# ---------------------------------------------------------------------------
# RDKit render kernel(唯一 owner; 逐行搬运自 api/mol.py)
# ---------------------------------------------------------------------------

def smiles_to_svg(smiles: str, width: int = 400, height: int = 300) -> str | None:
    """Render a SMILES string to an SVG string.

    计算体护栏与 reaction_to_svg 同款: RDKit 绘制器对合法但结构怪的
    分子也可能抛异常, 捕获后返回 None(消费方 REST→400 / MCP→ToolError)。
    """
    try:
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
    except Exception:
        return None


def smiles_to_png(smiles: str, width: int = 400, height: int = 300) -> bytes | None:
    """Render a SMILES string to PNG bytes (Cairo backend).

    Used for share-card (Open Graph) images: social platforms do not
    accept SVG as og:image.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    AllChem.Compute2DCoords(mol)
    drawer = Draw.rdMolDraw2D.MolDraw2DCairo(width, height)
    opts = drawer.drawOptions()
    opts.bondLineWidth = 2
    opts.scaleBondWidth = False
    opts.padding = 0.12
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


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
