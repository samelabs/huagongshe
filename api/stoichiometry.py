"""Reaction stoichiometry calculator — role-based dosing table via RDKit.

Anchors the mole basis on ANY chosen component (limiting reagent, or the
product for reverse scaling), then converts every component to mmol and mass
by its eq ratio. Honest boundaries: volume→mass needs density we don't have,
so concentration-derived solvent dosing reports volume only; product yield is
theoretical (100% conversion).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from rdkit import Chem
from rdkit.Chem import Descriptors

from .core.config import settings
from .core.rate_limit import enforce
from .core.security import Actor, internal_or_actor, optional_actor
from .schemas.stoichiometry import Component, Basis, ScaleInput, Role, Unit

router = APIRouter(tags=["stoichiometry"])

_PER_MOL = {"g": 1.0, "mg": 1e-3, "mol": 1.0, "mmol": 1e-3}


def _parse(smiles: str, role: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(400, f"{role}的 SMILES 无法解析：{smiles[:120]}")
    return mol


@router.post("/stoichiometry/scale", operation_id="calculate_stoichiometry")
async def calculate_stoichiometry(
    body: ScaleInput,
    actor: Actor | None = Depends(internal_or_actor),
) -> dict:
    """Scale a batch from a chosen basis component to a full role-based dosing table."""
    identity = f"u{actor.id}" if actor else "anon"
    await enforce("stoich", identity, settings.api_stoich_limit_per_minute, 60)

    if body.basis.index >= len(body.components):
        raise HTTPException(400, f"基准 index {body.basis.index} 超出组分范围")

    for i, c in enumerate(body.components):
        if c.role != "SOLVENT" and c.eq is None:
            raise HTTPException(400, f"组分 {i + 1}（{c.role}）缺少 eq（仅溶剂可留空）")

    solvent_rows = [i for i, c in enumerate(body.components) if c.role == "SOLVENT"]
    if body.concentration_mol_per_l is not None and len(solvent_rows) > 1:
        raise HTTPException(400, "按浓度定容仅支持单一溶剂行")

    mols = []
    for i, c in enumerate(body.components):
        mols.append(_parse(c.smiles, f"组分 {i + 1}（{c.role}）"))

    b = body.basis.index
    basis_mm = Descriptors.MolWt(mols[b])
    if body.basis.amount_unit in ("g", "mg"):
        basis_moles = body.basis.amount_value * _PER_MOL[body.basis.amount_unit] / basis_mm
    else:
        basis_moles = body.basis.amount_value * _PER_MOL[body.basis.amount_unit]

    total_volume_ml = (
        round(basis_moles / body.concentration_mol_per_l * 1000, 3)
        if body.concentration_mol_per_l is not None
        else None
    )

    out = []
    yield_g = None
    for i, c in enumerate(body.components):
        mm = Descriptors.MolWt(mols[i])
        eq_eff = 1.0 if i == b else c.eq  # 基准行恒 1.00 eq（由 basis 摩尔量定义），与响应 basis.mass_g 自洽
        entry = {
            "role": c.role,
            "smiles": c.smiles,
            "label": c.label,
            "formula": Chem.rdMolDescriptors.CalcMolFormula(mols[i]),
            "molar_mass": round(mm, 4),
            "exact_mass": round(Descriptors.ExactMolWt(mols[i]), 6),
            "eq": 1.0 if i == b else c.eq,
            "is_basis": i == b,
            "mmol": round(eq_eff * basis_moles * 1e3, 6) if eq_eff is not None else None,
            "mass_g": round(eq_eff * basis_moles * mm, 6) if eq_eff is not None else None,
            "volume_ml": total_volume_ml if (c.role == "SOLVENT" and c.eq is None and total_volume_ml is not None) else None,
        }
        if c.role == "PRODUCT" and eq_eff is not None and yield_g is None:
            yield_g = round(eq_eff * basis_moles * mm, 6)
        out.append(entry)

    return {
        "basis": {
            "index": b,
            "role": body.components[b].role,
            "smiles": body.components[b].smiles,
            "formula": Chem.rdMolDescriptors.CalcMolFormula(mols[b]),
            "molar_mass": round(basis_mm, 4),
            "moles": round(basis_moles, 9),
            "mmol": round(basis_moles * 1e3, 6),
            "mass_g": round(basis_moles * basis_mm, 6),
        },
        "components": out,
        "product_theoretical_yield_g": yield_g,
        "solvent_volume_ml": total_volume_ml,
        "note": "基准组分摩尔量为 1.00 eq；各组分量 = eq × 基准摩尔量 × 各自摩尔质量。产物为理论收率（100% 转化）；溶剂按浓度定容只给体积（无密度数据，不折算质量）。",
    }
