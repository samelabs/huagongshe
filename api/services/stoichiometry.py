"""Transport-neutral stoichiometry calculation service (G2.1).

自 api/stoichiometry.py 下沉, 业务计算逻辑零改动(逐行搬运)。
禁止导入 fastapi/mcp/Request/Response/UploadFile/HTTPException ——
status code / ToolError / headers 全部留 transport adapter。

输入 = ScaleInput DTO(api/schemas/stoichiometry.py, HTTP/MCP 两入口共用,
Pydantic 为共享 schema 层非 transport 私有); 输出 = 普通 dict。
业务校验用 ValueError, 消息与基线 HTTP detail 逐字一致, 由各 adapter
映射回自己的错误表达; 限流(enforce)是 entrypoint policy, 留在 adapter。
"""

from __future__ import annotations

import asyncio

from rdkit import Chem
from rdkit.Chem import Descriptors

from ..schemas.stoichiometry import ScaleInput

_PER_MOL = {"g": 1.0, "mg": 1e-3, "mol": 1.0, "mmol": 1e-3}


def _parse(smiles: str, role: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"{role}的 SMILES 无法解析：{smiles[:120]}")
    return mol


def validate(body: ScaleInput) -> None:
    """业务校验(transport-neutral): 消息与基线 HTTP 400 detail 逐字一致。"""
    if body.basis.index >= len(body.components):
        raise ValueError(f"基准 index {body.basis.index} 超出组分范围")

    for i, c in enumerate(body.components):
        if c.role != "SOLVENT" and c.eq is None:
            raise ValueError(f"组分 {i + 1}（{c.role}）缺少 eq（仅溶剂可留空）")

    solvent_rows = [i for i, c in enumerate(body.components) if c.role == "SOLVENT"]
    if body.concentration_mol_per_l is not None and len(solvent_rows) > 1:
        raise ValueError("按浓度定容仅支持单一溶剂行")


async def compute(body: ScaleInput) -> dict:
    # P1修复(搬运): RDKit 解析/分子量计算丢线程池 — schemas 允许 20000 字符×30
    # 组分, 病态 SMILES 同步解析会阻塞整个事件循环(两 worker 全卡)。
    # 与 1fb9daa 对 canonicalize_smiles 的处理同口径。
    validate(body)
    return await asyncio.to_thread(_compute, body)


def _compute(body: ScaleInput) -> dict:
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
