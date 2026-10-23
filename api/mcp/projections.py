"""MCP 对外输出映射：显式白名单投影，内部键不外泄。"""

from typing import Any

from ..services.field_labels import field_label

# 化合物详情对外的键集合(= 本投影当前实际输出; 服务层内部键
# similarity/follower_count/is_following/enrichment 不在其中)。
_CHEMICAL_PUBLIC_KEYS = (
    "id", "pubchem_cid", "smiles", "pubchem_smiles",
    "preferred_name", "name_cn", "name_local", "iupac_name",
    "molecular_formula", "average_mass", "monoisotopic_mass",
    "inchikey", "dtxsid", "cas_numbers", "nikkaji_numbers",
    "chembl_ids", "ec_numbers", "unii_codes", "chebi_ids",
    "synonym_count", "synonyms", "reaction_count", "details",
)

# 反应详情对外的键集合(服务层的 moderation_status/ord_record_id/
# dataset_name/is_following/follower_count 等内部键不在其中)。
_REACTION_PUBLIC_KEYS = (
    "id", "reaction_smiles", "visibility", "created_at", "updated_at",
    "ord_id", "source_type", "doi", "patent", "publication_url",
    "source_citation", "procedure_details", "safety_notes", "reflux",
    "ph", "conditions_detail", "temperature", "duration", "atmosphere",
    "pressure", "workup_details", "note", "creator", "is_owner",
    "participants", "workup",
)
# creator 子对象对外的键集合(avatar_url/is_following 是网页社交态)。
_REACTION_CREATOR_PUBLIC_KEYS = ("username", "display_name", "active")


def _evidence_values(values: Any) -> list[str]:
    out: list[str] = []
    for item in values if isinstance(values, list) else [values]:
        if isinstance(item, dict):
            text = item.get("value")
            if text is None:
                continue
            unit = item.get("unit")
            out.append(f"{text} {unit}" if unit else str(text))
        elif item is not None:
            out.append(str(item))
    return out


def _evidence(block: Any) -> dict[str, list[str]] | None:
    if not isinstance(block, dict) or not block:
        return None
    entries = block.get("entries") if isinstance(block.get("entries"), dict) else block
    out = {
        str(path): vals for path, raw in entries.items()
        if path not in ("references", "normalization")
        for vals in [_evidence_values(raw)] if vals
    }
    return out or None


def _notes(items: Any) -> list[dict[str, str]]:
    return [{"title": i.get("title"), "text": i.get("text")}
            for i in (items or []) if isinstance(i, dict)]


def _normalized_labels(raw: Any) -> Any:
    """标签字典 → 规范英文字段名(field_label); 不同原始键规范化后同名时
    合并为一键, 值以 '; ' 连接。非字典/空字典原样返回。"""
    if not isinstance(raw, dict) or not raw:
        return raw
    merged: dict[str, Any] = {}
    for key, value in raw.items():
        label = field_label(key) if isinstance(key, str) else str(key)
        if label in merged:
            merged[label] = f"{merged[label]}; {value}"
        else:
            merged[label] = value
    return merged


def _public_details(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    names, props = d.get("names") or {}, d.get("properties") or {}
    safety, industry = d.get("safety") or {}, d.get("industry") or {}
    identity = names.get("cb_identity") or {}
    updown = industry.get("cb_updown") or {}
    pb_safety = safety.get("pb_sections") or {}
    pb_industry = industry.get("pb_sections") or {}
    return {
        "description": (d.get("description") or {}).get("record_description"),
        "names": {
            "chinese_name": identity.get("cn"),
            "english_name": identity.get("en"),
            "formula": identity.get("formula"),
            "molecular_weight": identity.get("mw"),
            "aliases": [a.get("value") for a in names.get("cb_aliases") or []
                        if isinstance(a, dict) and a.get("value")],
        },
        "computed_properties": props.get("pb_computed"),
        "experimental_properties": _evidence(props.get("pb_physical_properties")),
        "physical_data": [
            {"name": field_label(p["label"]) if isinstance(p.get("label"), str) else p.get("label"),
             "value": p.get("text"),
             "numeric_value": p.get("v"), "unit": p.get("unit")}
            for p in props.get("cb_experimental") or [] if isinstance(p, dict)
        ],
        "chemical_properties": _notes(props.get("cb_prose")),
        "safety": {
            "ghs_classification": _evidence(pb_safety.get("ghs_classification")),
            "hazards": _evidence(pb_safety.get("hazards")),
            "safety_measures": _evidence(pb_safety.get("safety_measures")),
            "toxicity": _evidence(pb_safety.get("toxicity")),
            "regulatory": _evidence(pb_safety.get("regulatory")),
            "safety_data": _normalized_labels(safety.get("cb_safety")),
            "toxicity_notes": _notes(safety.get("cb_toxicity")),
            "storage_and_transport": _notes(safety.get("cb_packaging")),
        },
        "applications": {
            "pharmacology": _evidence(pb_industry.get("pharmacology")),
            "uses_and_manufacturing": _evidence(pb_industry.get("uses_and_manufacturing")),
            "uses": _notes(industry.get("cb_uses")),
            "preparation": _notes(industry.get("cb_preparation")),
            "handling_notes": _notes(industry.get("cb_notes")),
        },
        "related_products": {
            "upstream_materials": [n.get("name") for n in updown.get("up") or [] if isinstance(n, dict)],
            "downstream_products": [n.get("name") for n in updown.get("down") or [] if isinstance(n, dict)],
        },
        "reagent_prices": [
            {k: r.get(k) for k in ("code", "name", "package", "price", "updated")}
            for r in industry.get("cb_price") or [] if isinstance(r, dict)
        ],
        "suppliers": [
            {"name": s.get("name"), "phone": s.get("phone"), "email": s.get("email"),
             "website": s.get("website"), "purity": s.get("purity"),
             "package_price": s.get("pack_price"), "remark": s.get("remark")}
            for s in (d.get("suppliers") or {}).get("items") or [] if isinstance(s, dict)
        ],
    }


def _public_chemical(result: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in result.items() if k in _CHEMICAL_PUBLIC_KEYS}
    if "details" in out:
        out["details"] = _public_details(out["details"])
    return out


def _public_compound(c: dict[str, Any]) -> dict[str, Any]:
    """反应参与物 / 搜索命中的化合物: 去掉恒空的 similarity 槽位(相似度检索时保留实值)。"""
    return {k: v for k, v in c.items() if not (k == "similarity" and v is None)}


def _public_reaction(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in r.items() if k in _REACTION_PUBLIC_KEYS}
    creator = out.get("creator")
    if isinstance(creator, dict):
        out["creator"] = {k: v for k, v in creator.items()
                          if k in _REACTION_CREATOR_PUBLIC_KEYS}
    if "participants" in r:
        out["participants"] = [_public_compound(p) for p in r.get("participants") or []]
    return out


def _public_search(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in data.items()
           if k not in ("cas_fetch_pending", "cas_fetch_chemical_id")}
    if data.get("cas_fetch_pending"):
        out["lookup_pending"] = True
    out["chemicals"] = [_public_compound(c) for c in data.get("chemicals") or []]
    out["reactions"] = [
        {**{k: v for k, v in rx.items() if k != "match_basis"},
         **({"dataset_name": "User submitted"}
            if rx.get("dataset_name") == "user_submitted" else {})}
        for rx in data.get("reactions") or []
    ]
    return out


def _public_skill(s: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in s.items() if k not in ("origin", "owner_id")}


def _clean_doc(doc: str | None) -> str | None:
    """工具描述去掉 docstring 缩进与首尾/行尾空白。

    嵌套定义的 docstring 首行贴着三引号(无缩进), 其余行带 8 空格缩进,
    textwrap.dedent 对这种形态的公共前缀是空串 —— 改为按"第二行起的
    最小缩进"切齐, 逐行去行尾空白。
    """
    if not doc:
        return doc
    lines = doc.strip().splitlines()
    if len(lines) > 1:
        indents = [len(line) - len(line.lstrip())
                   for line in lines[1:] if line.strip()]
        cut = min(indents) if indents else 0
        lines = [lines[0].rstrip()] + [line[cut:].rstrip() for line in lines[1:]]
    return "\n".join(lines).strip()
