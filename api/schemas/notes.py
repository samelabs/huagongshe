"""Pydantic request models for Notes."""

from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_NOTE_REFERENCES = 20
MAX_NOTE_CONTENT_LENGTH = 30000


def sanitize_note_content(value: str) -> str:
    """Server-authoritative content normalization for Note create/update.

    - CRLF / CR newlines are normalized to LF.
    - LF (\\n) and TAB (\\t) are preserved.
    - All other Unicode Cc control characters are removed.
    - All Unicode Cf format characters (BOM, ZWJ, ZWNJ, direction marks, ...)
      are removed. Consequences, accepted by design: ZWJ-composed emoji
      sequences are not preserved byte-for-byte, and stored content is
      canonical (no invisible formatting characters).
    - CJK text, kana, hangul, SMILES and ordinary emoji pass through unchanged.
    """
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for ch in value:
        category = unicodedata.category(ch)
        if category == "Cc" and ch not in ("\n", "\t"):
            continue
        if category == "Cf":
            continue
        kept.append(ch)
    return "".join(kept)


class NoteBody(BaseModel):
    visibility: Literal["public", "private"] = "private"
    # No Field max_length here: the limit is enforced AFTER sanitization in
    # normalize_content (R4). A declared max_length would run first and
    # wrongly reject raw input >30000 whose sanitized form fits.
    content: str = Field(min_length=1)
    chemical_ids: list[int] = Field(default_factory=list)
    reaction_ids: list[int] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        # R4: sanitize FIRST, then apply the final length cap so that a raw
        # payload over 30000 chars which fits after Cf/Cc removal is accepted,
        # and anything still over 30000 after sanitization is rejected.
        value = sanitize_note_content(value).strip()
        if not value:
            raise ValueError("笔记内容不能为空")
        if len(value) > MAX_NOTE_CONTENT_LENGTH:
            raise ValueError(f"笔记内容不能超过 {MAX_NOTE_CONTENT_LENGTH} 字符")
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
