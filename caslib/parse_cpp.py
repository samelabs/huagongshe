"""CPP 页统一解析器(2026-09-05 规范化定案) — 五语言同构, 一套解析。

目标页: ChemicalProductProperty_{CN,EN,JP,DE,KR}_CB{cb}.htm (唯一采集目标)。
CAS 页职能只剩发现 cb_number, 不再解析内容。

分区(按页面官方结构, 白名单之外不采):
- identity   头区 dl<dt>键:</dt><dd>值</dd>: 中文名/英文名/别名/分子式/分子量/MOL链接
- properties ChemicalProperties 表, PropertyNameLabel_N ↔ PropertyValueLabel_N
             按 LabelID 配对(根治 dt/dd 顺序正则的配对漂移)
- safety     SafetyInformation 外层表 th/td
- price      ProductReagentPrice 表(更新日期/编号/名称/包装/价格固定列)
- updown     上游原料/下游产品 h3 区, {name, cb_number}(对方CB号页面原生给出)
- prose      h3 白名单标题区(用途/生产方法/化学性质等)

canonical 键: props 的页面标签 → 稳定英文键(键表见 _PROP_KEY); 未收录标签
保原文 label 不强行归类。数值化 v/unit 单源函数(PB exp_props 派生链已废)。
"""

from __future__ import annotations

import re
from typing import Any

from .parse import text_of, _balanced_table


# ---------------------------------------------------------------- canonical

# properties 页面标签(去尾冒号) → canonical 键。高频键实测178种, 收录确定性
# 物化性质/标识/数据库引用; 长尾不认识的标签保原文 label。
_PROP_KEY = {
    # 物化性质
    "密度": "density", "沸点": "bp", "熔点": "mp", "闪点": "flash_point",
    "蒸气压": "vapor_pressure", "蒸气密度": "vapor_density", "折射率": "refractive_index",
    "溶解度": "solubility", "水溶解性": "water_solubility", "溶解性": "solubility_note",
    "酸度系数(pKa)": "pka", "解离常数": "pka_note", "LogP": "logp",
    "形态": "form", "颜色": "color", "外观": "appearance", "外观性状": "appearance",
    "外观性质": "appearance", "性状": "appearance", "气味 (Odor)": "odor",
    "嗅觉阈值(Odor Threshold)": "odor_threshold", "香型": "odor_type",
    "比重": "specific_gravity", "旋光度 (Optical Rotation)": "optical_rotation",
    "比旋光度": "optical_rotation", "旋光度": "optical_rotation",
    "PH值": "ph", "介电常数": "dielectric_constant",
    "Dielectric constant": "dielectric_constant",
    "表面张力": "surface_tension", "比热容": "specific_heat", "热导率": "thermal_conductivity",
    "凝固点": "freezing_point", "升华点": "sublimation_point",
    "爆炸极限值(explosive limit)": "explosive_limit", "堆积密度": "bulk_density",
    "松密度": "bulk_density", "储存条件": "storage", "存储注意事项": "storage_note",
    "储存方法": "storage", "储藏": "storage", "贮存": "storage",
    "稳定性": "stability", "敏感性": "sensitivity", "水解敏感性": "hydrolytic_sensitivity",
    "生物来源": "biological_source", "主要应用": "main_application",
    "化妆品成分功效": "cosmetic_function", "化妆品成分评估": "cosmetic_assessment",
    "暴露限值": "exposure_limit", "检测方法": "detection_method",
    "最大波长(λmax)": "lambda_max", "吸收波长": "absorption_wavelength",
    "Absorption": "absorption", "ε(消光系数)": "extinction_coefficient",
    "Φ(量子产率)": "quantum_yield", "激发峰(Ex)/发射峰(Em)": "ex_em_peak",
    "Fluorescene": "fluorescence", "Flame Color": "flame_color",
    "电阻率 (resistivity)": "resistivity", "电导率": "conductivity",
    "相对极性": "relative_polarity", "酸碱指示剂变色ph值范围": "ph_transition_range",
    "Ksp沉淀平衡常数": "ksp", "Henry's Law Constant": "henry_law_constant",
    "旋光性": "optical_activity", "晶系": "crystal_system", "空间群": "space_group",
    "晶格常数": "lattice_constant", "晶体结构": "crystal_structure",
    "半导体性质": "semiconductor_property", "序列": "sequence",
    "Specific Activity": "specific_activity", "BCS Class": "bcs_class",
    "Modulus of Elasticity": "elastic_modulus", "Shear Modulus": "shear_modulus",
    "Bulk Modulus": "bulk_modulus", "Poissons Ratio": "poissons_ratio",
    "Hardness, Vickers": "hardness_vickers", "Hardness, Mohs": "hardness_mohs",
    "Hardness, Brinell": "hardness_brinell", "Hardness, Rockwell A": "hardness_rockwell_a",
    "Hardness, Rockwell B": "hardness_rockwell_b", "Hardness, Rockwell C": "hardness_rockwell_c",
    "Knoop Microhardness": "knoop_microhardness",
    "Vickers Microhardness": "vickers_microhardness",
    "Pour Point": "pour_point", "Tg": "tg", "Decomposition": "decomposition",
    "湿度": "humidity", "亲水亲油平衡值(HLB值)": "hlb",
    # 标识/数据库引用(值仍是文本, 不数值化)
    "InChI": "inchi", "InChIKey": "inchikey", "SMILES": "smiles",
    "CAS 数据库": "cas_db_ref", "CAS Number Unlabeled": "cas_unlabeled",
    "BRN": "brn", "Merck": "merck", "RTECS号": "rtecs",
    "FEMA": "fema", "JECFA Number": "jecfa",
    "EPA化学物质信息": "epa_ref", "EPA Substance Registry System": "epa_ref",
    "NIST化学物质信息": "nist_ref", "色指数": "colour_index",
    "(IARC)致癌物分类": "iarc_class", "ECETOC JACC REPORT": "ecetoc_jacc",
    "海关HS编码": "hs_code",
}

# identity 头区 dt 标签(去尾冒号) → canonical 键
# 标签全部来自五语言真页实测(tests/fixtures/cpp_*.html), 非推测。
_IDENTITY_KEY = {
    "cn": ("中文名", "中文名称", "化学名", "Bezeichnung", "한글명"),
    "en": ("英文名", "英文名称", "Chemical Name", "Englisch Name", "英語名", "상품명"),
    "alias_cn": ("中文别名", "别名", "Synonyma", "동의어(한글)"),
    "alias_en": ("英文别名", "Synonyms", "英語别名", "동의어(영문)"),
    "formula": ("分子式", "化学式", "Molecular Formula", "Summenformel", "분자식"),
    "mw": ("分子量", "Molecular Weight", "Molgewicht", "포뮬러 무게"),
}
# 反查: 标签 → identity 键
_IDENTITY_LABELS = {lab: key for key, labs in _IDENTITY_KEY.items() for lab in labs}

# 语言页头区 dl 里的物性标签(实测 de/ja/ko) → canonical 键。
# CN 页物性在 ChemicalProperties 表(走 _PROP_PAIR_RE), 语言页物性混在头区 dl。
_PROP_KEY_L10N = {
    # de
    "Dichte": "density", "Siedepunkt": "bp", "Schmelzpunkt": "mp",
    "Flammpunkt": "flash_point", "Dampfdruck": "vapor_pressure",
    "Dampfdichte": "vapor_density", "Brechungsindex": "refractive_index",
    "Löslichkeit": "solubility", "Wasserlöslichkeit": "water_solubility",
    "pka": "pka", "LogP": "logp", "Farbe": "color", "Geruch (Odor)": "odor",
    "Geruchsart": "odor_type", "Wichte": "specific_gravity",
    "Oberflächenspannung": "surface_tension",
    "Spezifische Wärmekapazität": "specific_heat",
    "Explosionsgrenze": "explosive_limit", "Stabilität": "stability",
    "Aggregatzustand": "form", "storage temp.": "storage",
    "Biologische Quelle": "biological_source", "Major Application": "main_application",
    "Kosmetik-Inhaltsstoffe Funktionen": "cosmetic_function",
    "PH": "ph", "Dielectric constant": "dielectric_constant",
    "Odor Threshold": "odor_threshold",
    "CAS Datenbank": "cas_db_ref", "EPA chemische Informationen": "epa_ref",
    "NIST chemische Informationen": "nist_ref",
    # ja
    "密度": "density", "比重(密度)": "density", "沸点": "bp", "融点": "mp",
    "闪点": "flash_point", "蒸気圧": "vapor_pressure", "蒸気密度": "vapor_density",
    "屈折率": "refractive_index", "溶解性": "solubility_note",
    "水溶解度": "water_solubility", "酸解離定数(Pka)": "pka",
    "色": "color", "臭い (Odor)": "odor", "においのタイプ": "odor_type",
    "比重": "specific_gravity", "表面張力": "surface_tension",
    "比熱容量": "specific_heat", "爆発限界(explosive limit)": "explosive_limit",
    "安定性": "stability", "外見": "appearance", "貯蔵温度": "storage",
    "由来生物": "biological_source", "主な用途": "main_application",
    "化粧品成分の機能": "cosmetic_function", "PH": "ph",
    "臭気閾値(Odor Threshold)": "odor_threshold",
    "CAS データベース": "cas_db_ref", "EPAの化学物質情報": "epa_ref",
    "NISTの化学物質情報": "nist_ref",
    # ko
    "밀도": "density", "끓는 점": "bp", "녹는점": "mp", "인화점": "flash_point",
    "증기압": "vapor_pressure", "증기 밀도": "vapor_density",
    "굴절률": "refractive_index", "용해도": "solubility", "수용성": "water_solubility",
    "산도 계수 (pKa)": "pka", "색상": "color", "냄새": "odor",
    "냄새 유형": "odor_type", "물리적 상태": "form", "안정성": "stability",
    "저장 조건": "storage", "생물학적 소스": "biological_source",
    "주요 응용": "main_application", "화장품 원료 기능": "cosmetic_function",
    "수소이온지수(pH)": "ph", "비열": "specific_heat", "표면장력": "surface_tension",
    "폭발한계": "explosive_limit",
    # en (头区 dl 不含物性, 物性在 table2; 此处只收 db 引用类)
    "EPA": "epa_ref", "NIST": "nist_ref",
    # en table2 物性表实测标签(部分与 de/ko 通用)
    "Melting point": "mp", "Boiling point": "bp", "Flash point": "flash_point",
    "vapor density": "vapor_density", "vapor pressure": "vapor_pressure",
    "refractive index": "refractive_index", "solubility": "solubility",
    "Density": "density",
    "Water Solubility": "water_solubility", "pKa": "pka", "Color": "color",
    "Odor": "odor", "Specific Gravity": "specific_gravity",
    "Surface Tension": "surface_tension", "Specific Heat": "specific_heat",
    "Explosive Limit": "explosive_limit", "Stability": "stability",
    "Appearance": "appearance", "Storage Conditions": "storage",
    "storage temp.": "storage", "Dielectric Constant": "dielectric_constant",
    "FEMA": "fema", "JECFA Number": "jecfa",
}
_PROP_KEY.update(_PROP_KEY_L10N)

# 语言页安全表(info_list / Risk and Safety table2)标签 → canonical 键。
# CN 页 safety 走 SafetyInformation 表, 语言页安全区是独立 info_list 表。
_SAFETY_KEY_L10N = {
    "위험품 표기": "hazard_code", "위험 카페고리 넘버": "risk_code",
    "안전지침서": "safety_code",
    "Kennzeichnung gefährlicher": "hazard_code", "R-Sätze": "risk_code",
    "S-Sätze": "safety_code",
    "主な危険性": "hazard_code", "Rフレーズ": "risk_code", "Sフレーズ": "safety_code",
    "Hazard Codes": "hazard_code", "Risk Statements": "risk_code",
    "Safety Statements": "safety_code", "RIDADR": "ridadr",
    "유엔번호(UN No.)": "ridadr",
    "WGK Germany": "wgk", "WGK 독일": "wgk",
    "RTECS": "rtecs", "RTECS 番号": "rtecs", "RTECS 번호": "rtecs",
    "TSCA": "tsca", "HS Code": "hs_code", "HSコード": "hs_code",
    "Hazard Note": "hazard_note",
    "HazardClass": "hazard_class", "国連危険物分類": "hazard_class",
    "PackingGroup": "packing_group", "容器等級": "packing_group",
}
_PROSE_TITLES = (
    "用途", "生产方法", "制备", "化学性质", "概述", "简介", "应用",
    "毒性", "毒性分级", "急性毒性", "刺激数据", "职业标准",
    "储运特性", "可燃性危险特性", "爆炸物危险特性", "灭火剂", "类别",
    # 语言页实测标题(fixtures)
    "化学的特性", "説明", "解説", "一般的な説明", "天然物の起源", "来歴",
    "使用", "定義", "調製方法", "製造方法", "使用用途", "合成方法", "純化方法",
    "개요", "화학적 성질", "출처", "역사", "용도", "생산 방법", "정의",
    "제조 방법", "일반 설명", "순도시험", "확인시험", "정량법",
    "Description", "Occurrence", "History", "Uses", "Definition",
    "General Description", "Preparation", "Production Method",
    "Beschreibung", "Chemische Eigensc", "Verwenden", "Vorbereitung Met",
    "synthetische", "Allgemeine Besch",
)

_PROP_PAIR_RE = re.compile(
    r'ChemicalProperties_PropertyNameLabel_(\d+)">\s*([^<]+?)</span>\s*</dt>\s*'
    r'<dd>\s*<span[^>]*ChemicalProperties_PropertyValueLabel_\1">([\s\S]*?)</span>'
)
_PROP_PAIR_TAIL_RE = re.compile(
    r'PropertyNameLabel_(\d+)">([^<]+?)</span>\s*</dt>\s*'
    r'<dd>\s*<span[^>]*PropertyValueLabel_\1">([\s\S]*?)</span>'
)
_HEAD_DL_RE = re.compile(r'<dt>\s*([^<]+?)\s*</dt>\s*<dd>([\s\S]*?)</dd>')
_MOL_HREF_RE = re.compile(r"href='([^']+\.mol)'|href=\"([^\"]+\.mol)\"")
_ALIAS_SPLIT_RE = re.compile(r"[;；]")
_UPDOWN_LINK_RE = re.compile(r"ChemicalProductProperty_\w\w_CB(\d+)\.htm", re.I)
_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _norm_label(raw: str) -> str:
    """dt/标签原文 → 规整键: 去标签去空白去尾冒号(含全角)。"""
    label = text_of(raw).rstrip(":：").strip()
    return label


def _parse_number_from_text(text: str) -> tuple[float | None, str | None]:
    """'162 °C (lit.)' → (162.0, '°C')。单位=首数后首个非空白非数字 token
    (字母/°/%开头), 截到空白或括号。失败 (None, None)。与 PB 口径一致。

    引文守卫(0905): 唯一数字若在引文括号内——'Insoluble (NTP, 1992)'、
    'Pyrene is a solid. (EPA, 1998)'——那是来源年份不是量值, v 不存在。
    判据: 去掉所有 (...) 括号段后文本里不再含该数字。
    """
    stripped = re.sub(r"\([^)]*\)", " ", text)
    m = _NUM_RE.search(text)
    if not m:
        return None, None
    if m.group(1) not in stripped:
        return None, None  # 数字只活在引文括号里 → 无量值
    try:
        number = float(m.group(1))
    except ValueError:
        return None, None
    rest = text[m.end():].lstrip()
    unit = None
    if rest:
        um = re.match(r"([a-zA-Z°%μμ‰℃][^\s(（]*)", rest)
        if um:
            unit = um.group(1).rstrip(".") or None
    return number, unit


def parse_cpp_page(html: str | None, *, locale: str = "zh-CN") -> dict[str, Any] | None:
    """CPP 页(任意语言) → canonical entry。解析不出内容 → None(not_found)。

    页面有效性判定在 fetch 层(cpp_page_state), 本函数只做结构化。
    """
    if not html:
        return None
    entry: dict[str, Any] = {}

    # ── identity 头区 ──
    # 头区 dl 同时出现在 CN 页(头区)与语言页(de/ja/ko 头区混排物性, en 头区纯标识)。
    # 头区里命中 _IDENTITY_LABELS 的进 identity, 命中 _PROP_KEY 的进 props(语言页通道)。
    identity: dict[str, Any] = {}
    head_props: list[tuple[str, str]] = []
    head_zone = html[: html.find('id="ChemicalProperties"') if 'id="ChemicalProperties"' in html else 40000]
    for m in _HEAD_DL_RE.finditer(head_zone):
        label = _norm_label(m.group(1))
        value = text_of(m.group(2)).strip()
        if not label or not value:
            continue
        key = _IDENTITY_LABELS.get(label)
        if key in ("cn", "en", "formula"):
            if key == "formula":
                # en 页值带尾缀("C4H8O2 Lewis structure") — 只取化学式token
                value = value.split()[0] if value.split() else value
            identity.setdefault(key, value)
        elif key in ("alias_cn", "alias_en"):
            parts = [p.strip() for p in _ALIAS_SPLIT_RE.split(value) if p.strip()]
            if parts:
                identity.setdefault(key, parts)
        elif key == "mw":
            try:
                identity.setdefault("mw", float(value))
            except ValueError:
                pass
        elif label in _PROP_KEY:
            head_props.append((label, value))
        elif label.startswith("MOL"):
            pass  # mol_href 统一由 _MOL_HREF_RE 从链接提取
    mol = _MOL_HREF_RE.search(head_zone)
    if mol:
        identity["mol_href"] = mol.group(1) or mol.group(2)
    if identity:
        entry["identity"] = identity

    # ── properties ──
    # CN 页: ChemicalProperties 表 LabelID 配对; 语言页: 头区 dl 物性对(head_props)
    # + en 页 ChemicalProperties 无 LabelID, 物性在 table2 th/td。
    props: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _add_prop(label: str, raw_text: str) -> None:
        text = re.sub(r"\s+", " ", raw_text).strip()
        if not label or not text:
            return
        key = _PROP_KEY.get(label) or label
        if key in seen_keys:
            return
        seen_keys.add(key)
        item: dict[str, Any] = {"key": key, "label": label, "text": text}
        if key not in ("smiles", "inchi", "inchikey"):
            v, unit = _parse_number_from_text(text)
            if v is not None:
                item["v"] = v
            if unit:
                item["unit"] = unit
        props.append(item)

    for m in _PROP_PAIR_RE.finditer(html):
        _add_prop(_norm_label(m.group(2)), text_of(m.group(3)))
    if not props and head_props:
        for label, value in head_props:
            _add_prop(label, value)
    # en 语言页: table2 th/td 物性表(Melting point 等)
    if not props:
        for tm in re.finditer(r'<table[^>]*class="table2"[\s\S]*?</table>', html, re.I):
            for k, v in re.findall(
                r"<th[^>]*>([\s\S]*?)</th>\s*<td[^>]*>([\s\S]*?)</td>",
                tm.group(0), re.I,
            ):
                _add_prop(_norm_label(k), text_of(v))
    if props:
        entry["props"] = props

    # ── safety ──
    # CN 页: SafetyInformation 锚点表; 语言页: info_list 表(de/ja/ko 安全区)
    # 或 en 页 Risk and Safety h3 下的 table2。键走 _SAFETY_KEY_L10N,
    # 未收录标签保原文(与 props 同纪律)。
    def _safety_pairs(zone: str) -> dict[str, str]:
        pairs = re.findall(
            r"<th[^>]*>([\s\S]*?)</th>\s*<td[^>]*>([\s\S]*?)</td>", zone, re.I,
        )
        out: dict[str, str] = {}
        for k, v in pairs:
            key = _norm_label(k)
            value = re.sub(r"\s+", " ", text_of(v)).strip()
            if not key or not value:
                continue
            out[_SAFETY_KEY_L10N.get(key, key)] = value
        return out

    safety: dict[str, str] = {}
    sm = re.search(r"SafetyInformation[^>]*cellspacing", html)
    if sm:
        start = html.rfind("<table", 0, sm.start())
        span = _balanced_table(html, start) if start >= 0 else None
        if span:
            safety = _safety_pairs(html[span[0]: span[1]])
    if not safety:
        for im in re.finditer(r'<table[^>]*class="info_list"[\s\S]*?</table>', html, re.I):
            safety.update(_safety_pairs(im.group(0)))
            if safety:
                break
    if not safety:
        rm = re.search(r"<h3[^>]*>\s*Risk and Safety[\s\S]*?</table>", html, re.I)
        if rm:
            safety = _safety_pairs(rm.group(0))
    if safety:
        entry["safety"] = safety

    # ── price (ProductReagentPrice 表) ──
    pi = html.find('id="ProductReagentPrice"')
    if pi >= 0:
        zone = html[pi: pi + 20000]
        rows = re.findall(r"<tr>([\s\S]*?)</tr>", zone)
        price: list[dict[str, str]] = []
        for r in rows:
            cells = [text_of(c).strip() for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", r)]
            if len(cells) >= 6:
                price.append({
                    "updated": cells[0], "code": cells[1], "name": cells[2],
                    "cas": cells[3], "package": cells[4], "price": cells[5],
                })
        if price:
            entry["price"] = price

    # ── updown {name, cb_number} ──
    # h3 标题五语言实测: CN 上游原料/下游产品, en Raw materials/Preparation Products,
    # de Upstream-Materialien/Downstream Produ, ja 原材料/準備製品, ko 원자재/준비 용품。
    updown: dict[str, list[dict[str, Any]]] = {}
    for labels, key in (
        (("上游原料", "Raw materials", "Upstream-Materialien", "原材料", "원자재"), "up"),
        (("下游产品", "Preparation Products", "Downstream Produkte", "準備製品", "준비 용품"), "down"),
    ):
        zone = None
        for label in labels:
            lm = re.search(rf"<h3[^>]*>\s*{re.escape(label)}\s*</h3>([\s\S]*?)(?:<h[23][^>]*>|</div>\s*</div>)", html)
            if lm:
                zone = lm.group(1)
                break
        if zone is None:
            continue
        items: list[dict[str, Any]] = []
        for am in re.finditer(r"<a\s[^>]*>([\s\S]*?)</a>", lm.group(1)):
            name = text_of(am.group(1)).strip()
            if not name:
                continue
            href_m = re.search(r"href='([^']+)'|href=\"([^\"]+)\"", am.group(0))
            href = (href_m.group(1) or href_m.group(2)) if href_m else ""
            cb = _UPDOWN_LINK_RE.search(href or "")
            item: dict[str, Any] = {"name": name}
            if cb:
                item["cb_number"] = cb.group(1)
            items.append(item)
        items = [
            it for it in _clean_updown_structs(items)
        ]
        if items:
            updown[key] = items
    if updown:
        entry["updown"] = updown

    # ── prose (h3 白名单标题) ──
    prose: list[dict[str, str]] = []
    for m3 in re.finditer(r"<h3[^>]*>([\s\S]*?)</h3>", html):
        title = _norm_label(m3.group(1))
        if title not in _PROSE_TITLES:
            continue
        rest = html[m3.end(): m3.end() + 3000]
        stop = re.search(r"<h[23][^>]*>|<table|<dl>", rest)
        seg = rest[: stop.start()] if stop else rest
        text = re.sub(r"\s+", " ", text_of(seg)).strip()
        if text and len(text) > 4:
            prose.append({"title": title, "text": text})
    if prose:
        entry["prose"] = prose

    return entry or None


def _clean_updown_structs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """摘除供应商导航尾缀链接(与旧 _clean_updown_names 同口径, 结构体版)。"""
    return [it for it in items if not re.search(r"生产厂家$", it["name"])]
