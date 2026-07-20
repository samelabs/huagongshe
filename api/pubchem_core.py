"""Validated mapping from PubChem properties to stable chemicals fields."""

from __future__ import annotations

import math
import re
from typing import Any

INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


def number_or_none(value: Any, cast=float):
    try:
        parsed = cast(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, float) and not math.isfinite(parsed):
        return None
    return parsed


def text_or_none(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or len(normalized) > max_length:
        return None
    return normalized


def chemical_core_values(
    properties: dict[str, Any], *, record_title: Any = None
) -> dict[str, Any]:
    """Map verified PubChem properties onto stable, non-identity columns."""
    inchikey = text_or_none(properties.get("InChIKey"), max_length=27)
    if inchikey and not INCHIKEY_RE.fullmatch(inchikey):
        inchikey = None
    average_mass = number_or_none(properties.get("MolecularWeight"))
    monoisotopic_mass = number_or_none(properties.get("MonoisotopicMass"))
    return {
        "preferred_name": text_or_none(
            properties.get("Title") or record_title, max_length=1000
        ),
        "iupac_name": text_or_none(properties.get("IUPACName"), max_length=4000),
        "molecular_formula": text_or_none(
            properties.get("MolecularFormula"), max_length=500
        ),
        "average_mass": average_mass if average_mass is not None and average_mass > 0 else None,
        "monoisotopic_mass": (
            monoisotopic_mass
            if monoisotopic_mass is not None and monoisotopic_mass > 0
            else None
        ),
        "inchikey": inchikey,
    }
