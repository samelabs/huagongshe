"""Shared, deterministic chemistry parsing used at API trust boundaries."""

from __future__ import annotations

import re

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.error")

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
DTXSID_RE = re.compile(r"^DTXSID\d{7,12}$", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


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
