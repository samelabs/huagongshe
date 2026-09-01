"""PUG View 整包解析 (2026-09-01 定案: 一个请求拉整记录, 解析成结构化字段)。

规则(实测 CID 2244 验证, 346 节点):
- 递归 Section 树按 TOCHeading 精确匹配; 缺 heading = 该化合物无数据, 跳过不造空壳
- Value 取 Number[0] / StringWithMarkup[].String / DateISO8601[0]
- 分页: 实测无 Page/TotalPages; 解析器读到该字段时记日志, 不写翻页机制
产物 = complete payload: core(主表同步) + cas_numbers + synonyms + chemical_pub 各列
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("huagongshe-worker")

# 数值列: TOCHeading → payload 键 (Computed Properties 子节点, Value.Number[0])
_NUMERICAL = {
    "XLogP3": ("xlogp", float),
    "Topological Polar Surface Area": ("tpsa", float),
    "Complexity": ("complexity", float),
    "Hydrogen Bond Donor Count": ("hbd", int),
    "Hydrogen Bond Acceptor Count": ("hba", int),
    "Rotatable Bond Count": ("rotatable", int),
    "Heavy Atom Count": ("heavy", int),
    "Formal Charge": ("charge", int),
}

# 主表同步的 Descriptor 叶子 (Computed Descriptors)
_DESCRIPTORS = ["IUPAC Name", "InChI", "InChIKey", "SMILES", "Molecular Formula"]

# 外部 ID: Other Identifiers 子节点 → external_ids 键(去空格小写连字符)
_EXTERNAL_SKIP = {
    "CAS", "Deprecated CAS", "Nikkaji Number", "ChEMBL ID",
    "European Community (EC) Number", "UNII", "ChEBI ID", "DSSTox Substance ID",
}
# 主表已有专用数组列的外部 ID → payload 键
_MAIN_TABLE_IDS = {
    "Nikkaji Number": "nikkaji_numbers",
    "ChEMBL ID": "chembl_ids",
    "European Community (EC) Number": "ec_numbers",
    "UNII": "unii_codes",
    "ChEBI ID": "chebi_ids",
    "DSSTox Substance ID": "dtxsid",
}

# 实验性质 → exp_props 键 (值 {v,unit,cond}: 文本解析出数值+单位, 失败保原文)
_EXP_PROPS = {
    "Boiling Point": "bp",
    "Melting Point": "mp",
    "Flash Point": "flash_point",
    "Solubility": "solubility",
    "Density": "density",
    "Vapor Pressure": "vapor_pressure",
    "LogP": "logp",
    "Dissociation Constants": "pka",
    "Physical Description": "physical_desc",
}

# 暴露限值 → exp_limits 键
_EXP_LIMITS = {
    "Permissible Exposure Limit (PEL)": "pel",
    "Recommended Exposure Limit (REL)": "rel",
    "Threshold Limit Values (TLV)": "tlv",
    "Immediately Dangerous to Life or Health (IDLH)": "idlh",
}

# 反应性 → reactivity 键
_REACTIVITY = {
    "Air and Water Reactions": "air_water",
    "Hazardous Reactivities and Incompatibilities": "incompatible",
    "Reactive Group": "reactive_group",
    "Reactivity Profile": "profile",
}

# 证据子树(整棵保留, 沿用 entries 平铺形态) → chemical_pub 列
_EVIDENCE_TREES = {
    "Chemical and Physical Properties": "physical",
    "Toxicity": "toxicity",
    "Regulatory Information": "regulatory",
    "Pharmacology and Biochemistry": "pharmacology",
    "Use and Manufacturing": "uses",
    "Other Identifiers": "identifiers",
    "Names and Identifiers": "computed",
}

# Safety and Hazards 子树关键词分桶(沿用既有分桶规则)
_GHS_KEYS = ("ghs classification",)
_MEASURE_KEYS = (
    "first aid", "fire fighting", "accidental release", "handling and storage",
    "exposure control", "personal protection",
)


def _walk_sections(node: dict[str, Any]):
    """产出 (heading, section) 的生成器, 递归整棵树。"""
    for child in node.get("Section") or []:
        heading = str(child.get("TOCHeading") or "").strip()
        if heading:
            yield heading, child
        yield from _walk_sections(child)


def _find_all(record: dict[str, Any], heading: str):
    for h, section in _walk_sections(record):
        if h == heading:
            yield section


def _find_one(record: dict[str, Any], heading: str) -> dict[str, Any] | None:
    return next(iter(_find_all(record, heading)), None)


def _swm_string(value: dict[str, Any]) -> str | None:
    """Value.StringWithMarkup[].String 取全部, 拼接首条。"""
    items = value.get("StringWithMarkup") or []
    for item in items:
        text = str(item.get("String") or "").strip()
        if text:
            return text
    return None


def _swm_all(value: dict[str, Any]) -> list[str]:
    items = value.get("StringWithMarkup") or []
    out = []
    for item in items:
        text = str(item.get("String") or "").strip()
        if text:
            out.append(text)
    return out


def _num0(value: dict[str, Any]):
    numbers = value.get("Number") or []
    return numbers[0] if numbers else None


def _leaf_strings(section: dict[str, Any]) -> list[str]:
    out = []
    for info in section.get("Information") or []:
        text = _swm_string(info.get("Value") or {})
        if text:
            out.append(text)
    return out


def _leaf_texts_with_refs(section: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for info in section.get("Information") or []:
        value = info.get("Value") or {}
        text = _swm_string(value)
        refs = info.get("ReferenceNumber") or []
        if not isinstance(refs, list):
            refs = [refs]
        entry: dict[str, Any] = {}
        if text:
            entry["value"] = text
        unit = value.get("Unit")
        if unit:
            entry["unit"] = str(unit)
        if entry:
            entry["references"] = [str(r) for r in refs[:10]]
            out.append(entry)
    return out


def _parse_number_from_text(text: str) -> tuple[float | None, str | None]:
    """从实验性质文本里解析 数值+单位: '135 °C' → (135.0, '°C')。失败 (None,None)。"""
    import re
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([^\d\s].{0,14})?", text)
    if not match:
        return None, None
    try:
        number = float(match.group(1))
    except ValueError:
        return None, None
    unit = match.group(2).strip() if match.group(2) else None
    return number, unit


def _collect_evidence_tree(section: dict[str, Any]) -> dict[str, Any]:
    """子树 → {entries: {path: [values]}} 平铺(与既有渲染形态兼容), 预算截断。"""
    entries: dict[str, Any] = {}
    kept = 0
    budget = 150_000

    def walk(node: dict[str, Any], path: tuple[str, ...]):
        nonlocal kept, budget
        for child in node.get("Section") or []:
            heading = str(child.get("TOCHeading") or "").strip()
            current = path + ((heading,) if heading else ())
            values = _leaf_texts_with_refs(child)
            if values and current:
                if kept >= 400 or budget <= 0:
                    return
                kept += 1
                budget -= sum(len(str(v)) for v in values)
                entries[" > ".join(current)] = values
            walk(child, current)

    walk(section, ())
    return {"entries": entries}


def parse_whole_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    """整包 → complete payload。Record 缺失/空壳 → None(worker 报 pubchem_empty)。"""
    record = payload.get("Record") or {}
    if not record.get("Section"):
        return None
    if "TotalPages" in payload or any(
        k in record for k in ("Page", "TotalPages")
    ):
        log.warning("pug_view pagination marker present (unhandled by design): %s",
                    str(payload)[:200])

    out: dict[str, Any] = {}

    # ── 标量 ──
    out["record_title"] = record.get("RecordTitle")
    desc = _find_one(record, "Record Description")
    if desc:
        out["record_description"] = _swm_string(
            ((desc.get("Information") or [{}])[0].get("Value")) or {})
    from datetime import date as _date
    def _to_date(raw):
        try:
            return _date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None
    created = _find_one(record, "Create Date")
    if created:
        dates = ((created.get("Information") or [{}])[0].get("Value") or {}).get("DateISO8601") or []
        if dates:
            out["pubchem_created_on"] = _to_date(dates[0])
    modified = _find_one(record, "Modify Date")
    if modified:
        dates = ((modified.get("Information") or [{}])[0].get("Value") or {}).get("DateISO8601") or []
        if dates:
            out["pubchem_modified_on"] = _to_date(dates[0])

    # ── 数值列 (Computed Properties 子节点) ──
    for heading, (key, cast) in _NUMERICAL.items():
        section = _find_one(record, heading)
        if section:
            for info in section.get("Information") or []:
                number = _num0(info.get("Value") or {})
                if number is not None:
                    try:
                        out[key] = cast(number)
                    except (TypeError, ValueError):
                        pass
                    break

    # ── 主表 core (Computed Descriptors + 分子量) ──
    core: dict[str, Any] = {}
    for heading in _DESCRIPTORS:
        section = _find_one(record, heading)
        if section:
            text = _swm_string((section.get("Information") or [{}]).get(0, {}).get("Value") if section.get("Information") else {}) if False else (
                (section.get("Information") or [{}])[0].get("Value") or {}
            )
            value = _swm_string((section.get("Information") or [{}])[0].get("Value") or {})
            if heading == "Molecular Formula":
                core["MolecularFormula"] = value
            elif heading == "SMILES":
                core["SMILES"] = value
            elif heading == "InChIKey":
                core["InChIKey"] = value
            elif heading == "IUPAC Name":
                core["IUPACName"] = value
    mw = _find_one(record, "Molecular Weight")
    if mw:
        info = (mw.get("Information") or [{}])[0]
        value = info.get("Value") or {}
        text = _swm_string(value)
        if text:
            try:
                core["MolecularWeight"] = float(text)
            except ValueError:
                pass
    em = _find_one(record, "Exact Mass")
    if em:
        number = _num0((em.get("Information") or [{}])[0].get("Value") or {})
        if number is not None:
            core["MonoisotopicMass"] = number
    out["core"] = core

    # ── CAS (Other Identifiers > CAS; cb_number 空才写由服务端裁定) ──
    cas_values: list[str] = []
    for section in _find_all(record, "CAS"):
        for text in _leaf_strings(section):
            if text not in cas_values:
                cas_values.append(text)
    out["cas_numbers"] = cas_values or None

    # ── external_ids + 主表 ID 数组列 ──
    external: dict[str, Any] = {}
    main_ids: dict[str, list[str]] = {}
    for oi in _find_all(record, "Other Identifiers"):
        for child in oi.get("Section") or []:
            heading = str(child.get("TOCHeading") or "").strip()
            values = _leaf_strings(child)
            if not values or not heading:
                continue
            if heading in _EXTERNAL_SKIP:
                if heading in _MAIN_TABLE_IDS:
                    main_ids[_MAIN_TABLE_IDS[heading]] = values
                continue
            key = heading.lower().replace(" ", "_")
            external[key] = values[0] if len(values) == 1 else values
    out["external_ids"] = external
    out["main_table_ids"] = main_ids

    # ── synonyms (Depositor-Supplied Synonyms) ──
    synonyms: list[str] = []
    for section in _find_all(record, "Depositor-Supplied Synonyms"):
        for info in section.get("Information") or []:
            synonyms.extend(_swm_all(info.get("Value") or {}))
    out["synonyms"] = synonyms or None

    # ── GHS 码 ──
    ghs_codes: dict[str, Any] = {}
    ghs_section = _find_one(record, "GHS Classification")
    if ghs_section:
        import re as _re
        h_codes: list[str] = []
        p_codes: list[str] = []
        pictograms: list[str] = []
        signal = None
        for info in ghs_section.get("Information") or []:
            name = str(info.get("Name") or "")
            value = info.get("Value") or {}
            if name == "Signal":
                signal = _swm_string(value)
            elif name == "Pictogram(s)":
                for item in value.get("StringWithMarkup") or []:
                    for markup in item.get("Markup") or []:
                        extra = str(markup.get("Extra") or "").strip()
                        if extra and extra not in pictograms:
                            pictograms.append(extra)
            elif name == "GHS Hazard Statements":
                h_codes.extend(_re.findall(r"H\d{3}", _swm_string(value) or ""))
            elif name == "Precautionary Statement Codes":
                p_codes.extend(_re.findall(r"P\d{3}", _swm_string(value) or ""))
        ghs_codes = {
            "h_code": sorted(set(h_codes)),
            "p_code": sorted(set(p_codes)),
            "pictogram": pictograms,
        }
        if signal:
            ghs_codes["signal_word"] = signal
    out["ghs_codes"] = ghs_codes

    # ── exp_props (数值化: 文本解析 数值+单位+原文) ──
    exp_props: dict[str, Any] = {}
    for heading, key in _EXP_PROPS.items():
        section = _find_one(record, heading)
        if not section:
            continue
        infos = section.get("Information") or []
        if not infos:
            continue
        value = infos[0].get("Value") or {}
        text = _swm_string(value)
        if text is None:
            continue
        number, unit = _parse_number_from_text(text)
        entry: dict[str, Any] = {"text": text}
        if number is not None:
            entry["v"] = number
        unit = unit or (str(value["Unit"]) if value.get("Unit") else None)
        if unit:
            entry["unit"] = unit
        exp_props[key] = entry
    out["exp_props"] = exp_props

    # ── exp_limits ──
    exp_limits: dict[str, Any] = {}
    for heading, key in _EXP_LIMITS.items():
        section = _find_one(record, heading)
        if not section:
            continue
        texts = _leaf_strings(section)
        if texts:
            number, unit = _parse_number_from_text(texts[0]) if len(texts) == 1 else (None, None)
            entry: dict[str, Any] = {"text": "; ".join(texts[:3])}
            if number is not None:
                entry["v"] = number
                if unit:
                    entry["unit"] = unit
            exp_limits[key] = entry
    out["exp_limits"] = exp_limits

    # ── reactivity ──
    reactivity: dict[str, Any] = {}
    for heading, key in _REACTIVITY.items():
        section = _find_one(record, heading)
        if not section:
            continue
        texts = _leaf_texts_with_refs(section)
        if texts:
            reactivity[key] = texts[:6]
    out["reactivity"] = reactivity

    # ── 证据子树 ──
    for tree_heading, key in _EVIDENCE_TREES.items():
        section = _find_one(record, tree_heading)
        if section:
            out[key] = _collect_evidence_tree(section)

    # ── safety 分桶 (GHS/急救消防泄漏储存暴露 = 三列) ──
    safety_root = _find_one(record, "Safety and Hazards")
    if safety_root:
        ghs: dict[str, Any] = {}
        hazards: dict[str, Any] = {}
        measures: dict[str, Any] = {}

        def bucket(node: dict[str, Any], path: tuple[str, ...]) -> None:
            for child in node.get("Section") or []:
                heading = str(child.get("TOCHeading") or "").strip()
                current = path + ((heading,) if heading else ())
                values = _leaf_texts_with_refs(child)
                if values and current:
                    lower = " > ".join(current).lower()
                    if any(k in lower for k in _GHS_KEYS):
                        ghs[" > ".join(current)] = values
                    elif any(k in lower for k in _MEASURE_KEYS):
                        measures[" > ".join(current)] = values
                    else:
                        hazards[" > ".join(current)] = values
                bucket(child, current)

        bucket(safety_root, ())
        out["ghs"] = {"entries": ghs}
        out["hazards"] = {"entries": hazards}
        out["measures"] = {"entries": measures}

    # ── references (Record.Reference 整表) ──
    references: dict[str, Any] = {}
    for ref in record.get("Reference") or []:
        number = ref.get("ReferenceNumber")
        if number is not None:
            references[str(number)] = {
                k: ref[k] for k in ("SourceName", "Name", "URL", "Description")
                if ref.get(k) is not None
            }
    out["references"] = references

    return out
