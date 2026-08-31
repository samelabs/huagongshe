"""Pydantic 请求模型 — 自各路由文件集中, 逻辑零改动(批次2)。"""
from typing import Literal
from pydantic import BaseModel, Field

Role = Literal["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"]
Unit = Literal["g", "mg", "mol", "mmol"]

class Component(BaseModel):
    role: Role
    smiles: str = Field(min_length=1, max_length=20000)
    eq: float | None = Field(default=None, gt=0, le=1000)
    label: str | None = Field(default=None, max_length=80)



class Basis(BaseModel):
    index: int = Field(ge=0)
    amount_value: float = Field(gt=0, le=1e9)
    amount_unit: Unit = "g"



class ScaleInput(BaseModel):
    components: list[Component] = Field(min_length=1, max_length=30)
    basis: Basis
    concentration_mol_per_l: float | None = Field(default=None, gt=0, le=50)


