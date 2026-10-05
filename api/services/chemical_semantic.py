"""Chemical detail semantic projection (E9-B 1.4).

以后端实现机械承接 Design System v2 §6 已在 Web 验证过的 semantic-first
组合(chemicalSections.ts / chemicalEvidence.ts): 公开 detail 一级语义固定为
7 个 section, PB/CB 不是一级 JSON namespace。

硬约束(DSv2 §6.4, 逐字沿用): 不为视觉整合发明数据合并 —— 每条无法安全
归一的事实保留独立 value 并附 source; 禁止 PB 覆盖 CB / CB 覆盖 PB /
字段名相似静默合并冲突事实 / 发明新的 source priority。

实现方式 = 纯机械分组(白名单键), 不重算、不改写、不发明数据:
- description/overview: PB record_description(存量字段, 原样)
- names: canonical(主 payload 已有) + CB identity(cn/en/formula/mw/aliases)
- properties: PB computed descriptors + PB physical_properties + CB props/prose
- safety: PB ghs/hazards/safety_measures/toxicity/regulatory + CB safety/toxicity/packaging
- industry: PB pharmacology/uses_and_manufacturing + CB uses/preparation/updown/price/notes
- suppliers: CB suppliers(原样)
- provenance: 各 source 的 fetched_at/state
"""
from __future__ import annotations

from typing import Any

# PB evidence 语义块 —— 与 web/components/chemicalEvidence.ts 同一白名单
PB_EVIDENCE_SECTIONS = (
    "physical_properties", "«redacted:ghs_…»", "hazards", "safety_measures",
    "toxicity", "regulatory", "pharmacology", "uses_and_manufacturing",
)
PB_SAFETY_KEYS = ("«redacted:ghs_…»", "hazards", "safety_measures", "toxicity", "regulatory")
PB_INDUSTRY_KEYS = ("pharmacology", "uses_and_manufacturing")

# CB computed descriptors(存量 ChemicalDetails 字段, PB source)
PB_COMPUTED_KEYS = (
    "xlogp", "topological_polar_surface_area", "complexity",
    "hbond_donor_count", "hbond_acceptor_count", "rotatable_bond_count",
    "heavy_atom_count", "formal_charge",
)

# CB prose 语义分组 —— 与 web/components/chemicalSections.ts PROSE_GROUPS
# 白名单逐条同源(0905 解析层白名单), 不新增分组。
# 2026-10 CB locale 读取: 标题分类收口为单一规则源 caslib/parse_cpp.py
# classify_prose_title(parser 与本模块共用; 此处不再维护语言标题表)。
# caslib 位于仓库根(api 亦从根 sys.path 导入 caslib.fetch/parse_cpp)。
from caslib.parse_cpp import classify_prose_title as _cb_prose_group


def _is_prose_item(item: Any) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("title"), str)
            and isinstance(item.get("text"), str))


def _prose_split(entry: dict[str, Any] | None) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {
        "uses": [], "preparation": [], "properties": [],
        "toxicity": [], "packaging": [], "notes": [],
    }
    for item in (entry or {}).get("prose") or []:
        if _is_prose_item(item):
            out[_cb_prose_group(item["title"])].append(
                {"title": item["title"], "text": item["text"], "source": "cb"})
    return out


def _is_named_node(n: Any) -> bool:
    return isinstance(n, dict) and isinstance(n.get("name"), str)


def _is_price_row(r: Any) -> bool:
    return isinstance(r, dict) and isinstance(r.get("code"), str)


def _pb_evidence_block(block: Any) -> dict[str, Any] | None:
    """PB evidence block 原样透传(已由 display_details 限幅); 仅排除空块。"""
    if not isinstance(block, dict):
        return None
    return block or None


def build_semantic_detail(
    pb: dict[str, Any] | None,
    cb_entry: dict[str, Any] | None,
    cb_suppliers: list[dict[str, Any]] | None,
    pb_state: dict[str, Any],
    cb_state: dict[str, Any],
) -> dict[str, Any]:
    """组合统一 semantic detail。PB/CB 数据各保留独立 value + source 字段。

    pb = services/enrichment.fetch_details 行(或 display 投影); cb_entry =
    chemical_cb.entry(zh-CN); suppliers = chemical_supplier_listing 联查行。
    两源各自失败时对应输入为 None 且 state=unavailable —— 已有另一源照常返回。
    """
    pb = pb or {}
    cb_entry = cb_entry or {}
    identity = cb_entry.get("identity") if isinstance(cb_entry.get("identity"), dict) else {}
    prose = _prose_split(cb_entry if isinstance(cb_entry, dict) else None)

    # CB props: [{key,label,text,v?,unit?}] 原样保留(仅过滤明显非 dict 项)
    cb_props = [p for p in (cb_entry.get("props") or []) if isinstance(p, dict)]
    cb_safety = (cb_entry.get("safety")
                 if isinstance(cb_entry.get("safety"), dict) else None)

    properties_pb: dict[str, Any] = {}
    for key in PB_COMPUTED_KEYS:
        if pb.get(key) is not None:
            properties_pb[key] = pb[key]
    physical = _pb_evidence_block(pb.get("physical_properties"))
    if physical is not None:
        properties_pb["physical_properties"] = physical

    safety_pb = {k: _pb_evidence_block(pb.get(k)) for k in PB_SAFETY_KEYS}
    safety_pb = {k: v for k, v in safety_pb.items() if v is not None}
    industry_pb = {k: _pb_evidence_block(pb.get(k)) for k in PB_INDUSTRY_KEYS}
    industry_pb = {k: v for k, v in industry_pb.items() if v is not None}

    names_aliases = [a for a in [
        *(identity.get("alias_cn") or []),
        *(identity.get("alias_en") or []),
    ] if isinstance(a, str) and a]

    updown_raw = cb_entry.get("updown") if isinstance(cb_entry.get("updown"), dict) else {}
    updown = {
        "up": [n for n in (updown_raw.get("up") or []) if _is_named_node(n)],
        "down": [n for n in (updown_raw.get("down") or []) if _is_named_node(n)],
    }
    prices = [r for r in (cb_entry.get("price") or []) if _is_price_row(r)]

    return {
        "description": {
            "source": "pubchem",
            "record_description": pb.get("record_description"),
        },
        "names": {
            "cb_identity": {
                k: identity.get(k)
                for k in ("cn", "en", "formula", "mw") if identity.get(k) is not None
            } if identity else {},
            "cb_aliases": [{"value": a, "source": "cb"} for a in names_aliases],
        },
        "properties": {
            "pb_computed": {k: v for k, v in properties_pb.items()
                            if k != "physical_properties"} or None,
            "pb_physical_properties": properties_pb.get("physical_properties"),
            "cb_experimental": [
                {"label": p.get("label"), "text": p.get("text"),
                 "v": p.get("v"), "unit": p.get("unit"), "source": "cb"}
                for p in cb_props
            ],
            "cb_prose": prose["properties"],
        },
        "safety": {
            "pb_sections": safety_pb or None,
            "cb_safety": (
                {k: v for k, v in cb_safety.items()} if cb_safety else None
            ),
            "cb_toxicity": prose["toxicity"],
            "cb_packaging": prose["packaging"],
        },
        "industry": {
            "pb_sections": industry_pb or None,
            "cb_uses": prose["uses"],
            "cb_preparation": prose["preparation"],
            "cb_updown": updown,
            "cb_price": prices,
            "cb_notes": prose["notes"],
        },
        "suppliers": {
            "items": (cb_suppliers or []),
        },
        "provenance": {
            "pubchem": pb_state,
            "cb": cb_state,
        },
    }


# --- provider 状态归一(E9-B 1.5) -------------------------------------------

def normalize_source_state(raw: str | None) -> str:
    """单 source normalized state。no_cas/absent/fresh-negative → none(非 error)。

    输入覆盖两类 raw 词: orchestration 原生词(current/queued/stale/unavailable)
    与 cb/enrichment 服务词(fresh/no_cas/absent/negative)。
    """
    mapping = {
        "current": "current",
        "fresh": "current",
        "no_cas": "none",
        "absent": "none",
        "negative": "none",
        "queued": "queued",
        "stale": "stale",
        "unavailable": "unavailable",
    }
    return mapping.get(raw or "", "unavailable")


def overall_enrichment_status(pb_norm: str, cb_norm: str, cb_applicable: bool) -> str:
    """overall 状态(E9-B 1.5 冻结序):
    queued(任一 queued) > stale(无 queued 且任一 stale) >
    degraded(任一适用 source unavailable) > current。"""
    if "queued" in (pb_norm, cb_norm):
        return "queued"
    if "stale" in (pb_norm, cb_norm):
        return "stale"
    if pb_norm == "unavailable" or (cb_applicable and cb_norm == "unavailable"):
        return "degraded"
    return "current"
