"""Shared, deterministic chemistry parsing used at API trust boundaries."""

from __future__ import annotations

import re

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.error")

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
DTXSID_RE = re.compile(r"^DTXSID\d{7,12}$", re.I)


def canonicalize_smiles(value: str) -> str | None:
    value = value.strip()
    if not value or len(value) > 4000:
        return None
    mol = Chem.MolFromSmiles(value)
    return Chem.MolToSmiles(mol, canonical=True) if mol is not None else None
