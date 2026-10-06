"""Pydantic request models for Notes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_NOTE_REFERENCES = 20


class NoteBody(BaseModel):
    visibility: Literal["public", "private"] = "private"
    content: str = Field(min_length=1, max_length=30000)
    chemical_ids: list[int] = Field(default_factory=list)
    reaction_ids: list[int] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("笔记内容不能为空")
        return value

    @field_validator("chemical_ids", "reaction_ids")
    @classmethod
    def normalize_ids(cls, values: list[int]) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()
        for value in values:
            if value < 1:
                raise ValueError("关联实体 ID 必须为正整数")
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @model_validator(mode="after")
    def validate_reference_count(self):
        if len(self.chemical_ids) + len(self.reaction_ids) > MAX_NOTE_REFERENCES:
            raise ValueError(f"每条笔记最多关联 {MAX_NOTE_REFERENCES} 个实体")
        return self
