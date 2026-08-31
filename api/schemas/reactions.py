"""Pydantic 请求模型 — 自各路由文件集中, 逻辑零改动(批次2)。"""
from pydantic import BaseModel, Field, model_validator, field_validator
from typing import Literal

from ..chemistry import normalize_doi

class ParticipantBody(BaseModel):
    role: Literal["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"]
    smiles: str = Field(min_length=1, max_length=4000)
    occurrence_count: int = Field(default=1, ge=1, le=20)
    amount_value: float | None = Field(default=None, ge=0)
    amount_unit: str | None = Field(default=None, max_length=40)
    equivalents: float | None = Field(default=None, ge=0)
    concentration_value: float | None = Field(default=None, ge=0)
    concentration_unit: str | None = Field(default=None, max_length=40)
    yield_percent: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_fields(self):
        if self.yield_percent is not None and self.role != "PRODUCT":
            raise ValueError("只有产物可以填写收率")
        if (self.amount_value is None) != (self.amount_unit is None):
            raise ValueError("投料数值和单位必须同时填写")
        if (self.concentration_value is None) != (self.concentration_unit is None):
            raise ValueError("浓度数值和单位必须同时填写")
        return self



class ReactionBody(BaseModel):
    visibility: Literal["public", "private"]
    participants: list[ParticipantBody] = Field(min_length=2, max_length=100)
    procedure_details: str | None = Field(default=None, max_length=30000)
    conditions_detail: str | None = Field(default=None, max_length=10000)
    temperature_value: float | None = None
    temperature_unit: Literal["CELSIUS", "KELVIN"] | None = None
    duration_value: float | None = Field(default=None, gt=0)
    duration_unit: Literal["MINUTE", "HOUR", "DAY"] | None = None
    ph: float | None = Field(default=None, ge=0, le=14)
    atmosphere: str | None = Field(default=None, max_length=120)
    pressure_value: float | None = Field(default=None, gt=0)
    pressure_unit: str | None = Field(default=None, max_length=40)
    workup_details: str | None = Field(default=None, max_length=10000)
    safety_notes: str | None = Field(default=None, max_length=10000)
    source_type: Literal["self", "doi", "patent", "database", "url", "other"]
    doi: str | None = Field(default=None, max_length=300)
    patent: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=1000)
    source_citation: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=10000)

    @field_validator(
        "procedure_details", "conditions_detail", "atmosphere", "pressure_unit",
        "workup_details", "safety_notes", "patent", "source_url",
        "source_citation", "note",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        result = (value or "").strip()
        return result or None

    @field_validator("doi")
    @classmethod
    def clean_doi(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = normalize_doi(value)
        if not normalized:
            raise ValueError("DOI 格式不正确")
        return normalized

    @model_validator(mode="after")
    def validate_reaction(self):
        roles = {item.role for item in self.participants}
        if "REACTANT" not in roles or "PRODUCT" not in roles:
            raise ValueError("至少需要一个反应物和一个产物")
        if (self.temperature_value is None) != (self.temperature_unit is None):
            raise ValueError("温度数值和单位必须同时填写")
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("反应时间数值和单位必须同时填写")
        if (self.pressure_value is None) != (self.pressure_unit is None):
            raise ValueError("压力数值和单位必须同时填写")
        if self.source_url and not self.source_url.startswith(("http://", "https://")):
            raise ValueError("来源链接必须以 http:// 或 https:// 开头")
        requirements = {
            "doi": self.doi,
            "patent": self.patent,
            "url": self.source_url,
            "database": self.source_citation,
            "other": self.source_citation,
        }
        if self.source_type in requirements and not requirements[self.source_type]:
            raise ValueError(f"来源类型 {self.source_type} 缺少对应的来源信息")
        return self


