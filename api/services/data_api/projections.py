"""对外数据服务的输出投影。

化合物与反应的输出与站内详情页同一范式: 页面有哪些分区和字段、按什么
规则取值, 这里就输出同样的分区和字段; 标题/副标题与页面同一取名规则,
按 locale 返回, 缺失时英文兜底; 每个字段只出现一次, 不按来源区分。
"""

from __future__ import annotations

import re
from typing import Any

from .field_labels import field_key, field_label


# 安全字段落入五个安全分区的归类线索(按子串匹配; 未命中归 hazards)。
_SAFETY_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("toxicity", ("毒性", "toxicity", "ld50", "毒物", "有害物質", "giftige")),
    ("safety_measures", ("存储", "儲蔵", "保管", "storage", "安全说明", "safety_code",
                         "safety statements", "防护", "ppe", "包装", "packing",
                         "speicherklasse", "stor")),
    ("regulatory", ("法规", "規制", "wgk", "tsca", "海关", "税関", "hs_code",
                    "reach", "regulatory", "化管理", "법", "prtr", "化審")),
    ("ghs", ("ghs", "信号词", "signal word", "象形图", "危险说明", "hazard statements")),
]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_chinese_locale(locale: str) -> bool:
    return bool(re.match(r"^zh\b", (locale or "").strip(), re.I))


def resolve_title(chemical: dict[str, Any], locale: str) -> tuple[str, str | None]:
    """与站内详情页同一取名规则: 当地常用名 → 英文常用名 → IUPAC 名 →
    分子式 → CAS 号 → HCID; 主标题是当地名时副标题给英文常用名。"""
    local = _clean(chemical.get("name_local")) or (
        _clean(chemical.get("name_cn")) if _is_chinese_locale(locale) else None)
    common = _clean(chemical.get("preferred_name"))
    systematic = _clean(chemical.get("iupac_name"))
    formula = _clean(chemical.get("molecular_formula"))
    cas = _clean((chemical.get("cas_numbers") or [None])[0])

    if local:
        secondary = common and common.lower() != local.lower()
        return local, (common if secondary else None)
    for candidate in (common, systematic, formula, cas):
        if candidate:
            return candidate, None
    return f"HCID {chemical.get('id')}", None


def _evidence_rows(block: dict[str, Any] | None) -> list[dict[str, Any]]:
    """证据块 → 字段行(label 取路径末段; 值数组逐项取 value/name/description/text)。"""
    rows: list[dict[str, Any]] = []
    entries = (block or {}).get("entries") or {}
    if not isinstance(entries, dict):
        return rows
    for path, values in entries.items():
        if path in ("references", "normalization"):
            continue
        items = values if isinstance(values, list) else [values]
        texts: list[str] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, (str, int, float, bool)):
                texts.append(str(item))
            elif isinstance(item, dict):
                raw = item.get("value", item.get("name", item.get("description", item.get("text"))))
                if isinstance(raw, list):
                    joined = "；".join(str(v) for v in raw if v is not None)
                    if joined:
                        texts.append(joined)
                elif raw is not None:
                    texts.append(str(raw))
        if not texts:
            continue
        rows.append({"label": str(path).split(" > ")[-1], "values": texts})
    return rows


def _merge_rows(target: dict[str, dict[str, Any]], rows: list[dict[str, Any]],
                unit: str | None = None) -> None:
    """同名字段合并(规范字段名为键, 值去重追加; 标签统一为规范英文名)。"""
    for row in rows:
        label = field_label(row["label"])
        key = field_key(row["label"])
        existing = target.get(key)
        if existing:
            for value in row["values"]:
                if value not in existing["values"]:
                    existing["values"].append(value)
        else:
            target[key] = {"label": label, "values": list(row["values"]),
                           **({"unit": unit} if unit else {})}


def _safety_bucket(label: str) -> str:
    lowered = field_key(label)
    for bucket, needles in _SAFETY_BUCKETS:
        if any(n in lowered or n in label for n in needles):
            return bucket
    return "hazards"


def _data_status(detail: dict[str, Any]) -> str:
    enrichment = detail.get("enrichment") or {}
    status = enrichment.get("status")
    return "complete" if status in ("current", "negative", "no_cas", "absent") else "updating"


def _data_updated_at(detail: dict[str, Any]) -> str | None:
    provenance = ((detail.get("details") or {}).get("provenance") or {})
    stamps = []
    for source in provenance.values():
        if isinstance(source, dict) and source.get("fetched_at"):
            stamps.append(str(source["fetched_at"]))
    return max(stamps) if stamps else None


def project_chemical(detail: dict[str, Any], locale: str, *, site_origin: str) -> dict[str, Any]:
    """化合物详情 → 对外投影(分区与字段与站内详情页一致)。"""
    facts = detail.get("details") or {}
    names = facts.get("names") or {}
    properties = facts.get("properties") or {}
    safety = facts.get("safety") or {}
    industry = facts.get("industry") or {}

    title, subtitle = resolve_title(detail, locale)
    identity = names.get("cb_identity") or {}

    # 性质分区: 计算值 + 证据 + 实测值, 同一字段只出现一次。
    prop_fields: dict[str, dict[str, Any]] = {}
    computed = properties.get("pb_computed") or {}
    computed_map = [
        ("XLogP", "xlogp"), ("Topological polar surface area", "topological_polar_surface_area"),
        ("Hydrogen bond donor count", "hbond_donor_count"),
        ("Hydrogen bond acceptor count", "hbond_acceptor_count"),
        ("Rotatable bond count", "rotatable_bond_count"),
        ("Heavy atom count", "heavy_atom_count"), ("Formal charge", "formal_charge"),
        ("Complexity", "complexity"),
    ]
    for label, key in computed_map:
        if computed.get(key) is not None:
            _merge_rows(prop_fields, [{"label": label, "values": [str(computed[key])]}])
    _merge_rows(prop_fields, _evidence_rows(properties.get("pb_physical_properties")))
    for row in properties.get("cb_experimental") or []:
        value = row.get("text") or " ".join(
            part for part in (str(row["v"]) if row.get("v") is not None else None,
                              row.get("unit")) if part)
        _merge_rows(prop_fields, [{"label": row.get("label") or "—", "values": [value]}])
    for item in properties.get("cb_prose") or []:
        _merge_rows(prop_fields, [{"label": item.get("title") or "—",
                                   "values": [item.get("text") or ""]}])

    # 安全与法规分区: 五个安全分区, 各来源字段归类合并。
    safety_parts: dict[str, dict[str, dict[str, Any]]] = {
        key: {} for key in ("ghs", "hazards", "safety_measures", "toxicity", "regulatory")}
    pb_sections = safety.get("pb_sections") or {}
    section_targets = {
        "ghs_classification": "ghs", "hazards": "hazards",
        "safety_measures": "safety_measures", "toxicity": "toxicity",
        "regulatory": "regulatory",
    }
    for section_key, target in section_targets.items():
        _merge_rows(safety_parts[target], _evidence_rows(pb_sections.get(section_key)))
    for key, value in (safety.get("cb_safety") or {}).items():
        text = value if isinstance(value, str) else "; ".join(
            f"{k}: {v}" for k, v in (value or {}).items()) if isinstance(value, dict) else str(value)
        if text and text.strip():
            _merge_rows(safety_parts[_safety_bucket(key)], [{"label": key, "values": [text.strip()]}])
    for prose in ("cb_toxicity", "cb_packaging"):
        for item in safety.get(prose) or []:
            _merge_rows(safety_parts["toxicity"], [{"label": item.get("title") or "—",
                                                    "values": [item.get("text") or ""]}])

    # 化学与工业分区。
    updown = industry.get("cb_updown") or {}
    prices = [
        {"name": row.get("name"), "package": row.get("package"),
         "price": row.get("price"), "updated": row.get("updated")}
        for row in (industry.get("cb_price") or [])
    ]
    suppliers = [
        {"name": row.get("name"), "phone": row.get("phone"), "email": row.get("email")}
        for row in ((facts.get("suppliers") or {}).get("items") or [])
    ]

    return {
        "hcid": detail.get("id"),
        "title": title,
        "subtitle": subtitle,
        "cas": (detail.get("cas_numbers") or [None])[0],
        "formula": detail.get("molecular_formula"),
        "molecular_weight": detail.get("average_mass"),
        "structure_image": f"{site_origin}/img/chemical/{detail.get('id')}.png",
        "overview": {
            "description": facts.get("description"),
            "smiles": detail.get("smiles") or detail.get("pubchem_smiles"),
            "inchikey": detail.get("inchikey"),
            "iupac_name": detail.get("iupac_name"),
            "exact_mass": detail.get("monoisotopic_mass"),
        },
        "names": {
            "local_name": _clean(detail.get("name_local")) or (
                _clean(detail.get("name_cn")) if _is_chinese_locale(locale) else None),
            "english_name": _clean(identity.get("en")) or _clean(detail.get("preferred_name")),
            "synonyms": list(detail.get("synonyms") or []),
            "synonyms_total": detail.get("synonym_count") or len(detail.get("synonyms") or []),
            "identifiers": {
                "pubchem_cid": detail.get("pubchem_cid"),
                "cas_numbers": list(detail.get("cas_numbers") or []),
                "dtxsid": detail.get("dtxsid"),
                "ec_numbers": list(detail.get("ec_numbers") or []),
                "chebi_ids": list(detail.get("chebi_ids") or []),
                "chembl_ids": list(detail.get("chembl_ids") or []),
                "unii_codes": list(detail.get("unii_codes") or []),
                "nikkaji_numbers": list(detail.get("nikkaji_numbers") or []),
            },
        },
        "properties": list(prop_fields.values()),
        "safety": {key: list(rows.values()) for key, rows in safety_parts.items()},
        "industry": {
            "uses": [{"title": i.get("title"), "text": i.get("text")}
                     for i in (industry.get("cb_uses") or [])],
            "preparation": [{"title": i.get("title"), "text": i.get("text")}
                            for i in (industry.get("cb_preparation") or [])],
            "upstream": [row.get("name") for row in (updown.get("up") or [])],
            "downstream": [row.get("name") for row in (updown.get("down") or [])],
            "prices": prices,
        },
        "suppliers": suppliers,
        "data_status": _data_status(detail),
        "data_updated_at": _data_updated_at(detail),
    }


def project_reaction(reaction: dict[str, Any], locale: str, *, site_origin: str) -> dict[str, Any]:
    """反应详情 → 对外投影(只含公开反应; 分区与站内反应详情页一致)。"""
    participants = reaction.get("participants") or []
    reactants = [p for p in participants if p.get("role") == "REACTANT"]
    products = [p for p in participants if p.get("role") == "PRODUCT"]
    with_yield = [p for p in products if p.get("yield_percent") is not None]
    primary_product = (max(with_yield, key=lambda p: p["yield_percent"])
                       if with_yield else (products[0] if products else None))
    primary_reactant = reactants[0] if reactants else None

    def name_of(item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        text, _ = resolve_title(item, locale)
        return text

    left, right = name_of(primary_reactant), name_of(primary_product)
    if left and right:
        title = f"{left} → {right}"
    elif left:
        title = f"{left} →"
    elif right:
        title = f"→ {right}"
    else:
        title = f"HRID {reaction.get('id')}"

    def amount(participant: dict[str, Any]) -> dict[str, Any] | None:
        if participant.get("amount_value") is None:
            return None
        return {"value": participant.get("amount_value"),
                "unit": participant.get("amount_unit"),
                "equivalents": participant.get("equivalents")}

    conditions: dict[str, Any] = {
        "temperature": reaction.get("temperature"),
        "duration": reaction.get("duration"),
        "pressure": reaction.get("pressure"),
        "atmosphere": reaction.get("atmosphere"),
        "ph": reaction.get("ph"),
        "reflux": reaction.get("reflux"),
        "details": reaction.get("conditions_detail"),
    }

    return {
        "hrid": reaction.get("id"),
        "title": title,
        "equation_smiles": reaction.get("reaction_smiles"),
        "equation_image": f"{site_origin}/img/reaction/{reaction.get('id')}.svg",
        "visibility": reaction.get("visibility"),
        "participants": [
            {
                "role": p.get("role"),
                "name": name_of(p),
                "hcid": p.get("id"),
                "occurrence_count": p.get("occurrence_count"),
                "amount": amount(p),
                "yield_percent": p.get("yield_percent"),
            }
            for p in participants
        ],
        "conditions": conditions,
        "procedure": reaction.get("procedure_details"),
        "workup": reaction.get("workup_details"),
        "note": reaction.get("note"),
        "safety_notes": reaction.get("safety_notes"),
        "references": {
            "source_type": reaction.get("source_type"),
            "doi": reaction.get("doi"),
            "patent": reaction.get("patent"),
            "url": reaction.get("publication_url"),
            "citation": reaction.get("source_citation"),
        },
        "created_at": reaction.get("created_at"),
        "updated_at": reaction.get("updated_at"),
    }


def project_reaction_summary(row: Any) -> dict[str, Any]:
    """化合物参与反应的公开摘要行。"""
    return {
        "hrid": row[0],
        "equation_smiles": row[1],
        "visibility": row[2],
        "updated_at": str(row[3]) if row[3] is not None else None,
        "participant_count": row[4],
    }
