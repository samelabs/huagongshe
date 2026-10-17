"""Shared, deterministic chemistry parsing used at API trust boundaries."""

from __future__ import annotations

import re

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.error")

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
DTXSID_RE = re.compile(r"^DTXSID\d{7,12}$", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


def cas_checkdigit_valid(value: str) -> bool:
    """CAS 校验位: 检查位左侧逐位 ×1,2,3…(从右往左)求和 mod 10 == 末位。

    输入须已通过 CAS_RE 格式校验; 不匹配格式时行为未定义(调用方先判格式)。
    """
    digits = value.replace("-", "")
    total = sum(int(d) * (i + 1) for i, d in enumerate(reversed(digits[:-1])))
    return total % 10 == int(digits[-1])


def valid_cas(value: str | None) -> bool:
    """格式 + 校验位都合法的 CAS 才入库/入检索(入口只挡格式不够)。"""
    normalized = (value or "").strip()
    return bool(CAS_RE.fullmatch(normalized)) and cas_checkdigit_valid(normalized)


def normalize_doi(value: str | None) -> str | None:
    """Return the DOI name used for indexed storage and lookup."""
    normalized = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    if not DOI_RE.fullmatch(normalized):
        return None
    return normalized.lower()


def canonicalize_smiles(value: str) -> str | None:
    value = value.strip()
    if not value or len(value) > 4000:
        return None
    mol = Chem.MolFromSmiles(value)
    return Chem.MolToSmiles(mol, canonical=True) if mol is not None else None
