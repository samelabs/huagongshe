"""Worker-side structure comparison; the API repeats this validation."""

from __future__ import annotations

from rdkit import Chem, RDLogger
from typing import Any

RDLogger.DisableLog("rdApp.error")


def canonicalize_smiles(value: str) -> str | None:
    value = value.strip()
    if not value or len(value) > 4000:
        return None
    mol = Chem.MolFromSmiles(value)
    return Chem.MolToSmiles(mol, canonical=True) if mol is not None else None


def select_verified_cid(
    candidates: list[int],
    properties: list[dict[str, Any]],
    *,
    expected_cid: int | None,
    expected_smiles: str | None,
) -> int | None:
    """Pick the verified CID deterministically.

    Precedence:
    1. An explicitly expected CID wins when present in candidates and properties.
    2. A unique structure match (canonical SMILES equality) wins when exactly
       one candidate matches.
    3. Same structure filed under multiple records: pick the lowest CID — the
       oldest standing record — as a deterministic tiebreak, never a guess.
    """
    property_map = {
        int(item["CID"]): item
        for item in properties
        if item.get("CID") is not None
    }
    if expected_cid is not None:
        return expected_cid if expected_cid in candidates and expected_cid in property_map else None

    expected_structure = canonicalize_smiles(expected_smiles or "")
    if expected_structure:
        matching = []
        for cid, item in property_map.items():
            returned = item.get("SMILES") or item.get("ConnectivitySMILES")
            if canonicalize_smiles(str(returned or "")) == expected_structure:
                matching.append(cid)
        if len(matching) == 1:
            return matching[0]

    valid = [c for c in candidates if c in property_map]
    if valid:
        return min(valid)
    return None
