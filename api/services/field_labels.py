"""对外数据服务的字段名规范表。

数据里的字段标签有多种形态: 规范代码(wgk、tsca)、按来源语言本地化的
名称(熔点 / 融点 / Melting point / Schmelzpunkt)、证据路径末段。同一
字段在不同语言下标签不同 —— 这里把已知标签统一映射为中性英文字段名;
未收录的标签原样保留(多为专有名词)。
"""

from __future__ import annotations

# 规范字段名 → 参与匹配的原始标签(小写比较)。
_CANONICAL: dict[str, str] = {}


def _reg(canonical: str, *synonyms: str) -> None:
    for synonym in (canonical, *synonyms):
        _CANONICAL[synonym.strip().lower()] = canonical


# ── 性质字段 ─────────────────────────────────────────────────────────
_reg("Melting point", "熔点", "融点", "melting point", "schmelzpunkt", "녹는점")
_reg("Freezing point", "凝固点", "freezing point", "freezingpoint")
_reg("Boiling point", "沸点", "boiling point", "siedepunkt", "끓는 점")
_reg("Density", "密度", "比重(密度)", "density", "dichte", "밀도")
_reg("Bulk density", "堆积密度", "かさ密度", "bulk density")
_reg("Specific gravity", "比重", "specific gravity", "wichte")
_reg("Vapor pressure", "蒸气压", "蒸気圧", "vapor pressure", "dampfdruck", "증기압")
_reg("Vapor density", "蒸气密度", "蒸気密度", "vapor density", "dampfdichte", "증기 밀도")
_reg("Refractive index", "折射率", "屈折率", "refractive index", "brechungsindex", "굴절률")
_reg("Flash point", "闪点", "引火点", "flash point", "flammpunkt", "인화점")
_reg("pH", "ph", "ph值")
_reg("LogP", "logp")
_reg("pKa", "pka", "酸度系数(pka)", "酸解離定数(pka)")
_reg("Solubility", "溶解度", "溶解性", "水溶解度", "水溶解性", "solubility",
    "수용성", "löslichkeit", "wasserlöslichkeit", "water solubility")
_reg("Odor", "气味 (odor)", "臭い (odor)", "气味", "臭い", "냄새", "geruch (odor)", "odor")
_reg("Odor type", "香型", "臭いのタイプ", "냄새 유형", "geruchsart", "odor type")
_reg("Odor threshold", "嗅觉阈值(odor threshold)", "臭気閾値(odor threshold)", "odor threshold")
_reg("Taste", "味道", "taste")
_reg("Color", "颜色", "色", "색상", "farbe", "color")
_reg("Physical state", "形态", "外見", "物리적 상태", "aggregatzustand", "form")
_reg("Storage conditions", "储存条件", "貯蔵温度", "저장 조건", "storage temp.")
_reg("Stability", "稳定性", "安定性", "안정성", "stability", "stabilität")
_reg("Autoignition temperature", "自燃温度", "自然発火温度", "자연 발화 온도",
    "selbstentzündungstemperatur", "autoignition temperature")
_reg("Explosive limits", "爆炸极限值(explosive limit)", "爆発限界(explosive limit)",
    "폭발한계", "explosionsgrenze", "explosive limit")
_reg("Dielectric constant", "介电常数", "dielectric constant")
_reg("Specific heat capacity", "比热容", "比熱容量", "비열",
    "spezifische wärmekapazität", "specific heat capacity")
_reg("Thermal conductivity", "热导率", "thermal conductivity")
_reg("Henry's law constant", "henry's law constant", "亨利常数")
_reg("Major applications", "主要应用", "主な用途", "주요 응용", "major application")
_reg("Biological source", "生物来源", "由来生物", "생물학적 소스", "biological source")

# ── 安全与法规字段 ───────────────────────────────────────────────────
_reg("Water hazard class (WGK)", "wgk", "wgk germany")
_reg("TSCA inventory status", "tsca")
_reg("RTECS number", "rtecs", "rtecs号", "rtecs-nr.")
_reg("UN transport number", "ridadr", "危险品运输编号")
_reg("Packing group", "包装类别", "packinggroup", "packing_group", "포장분류")
_reg("Hazard class", "危险等级", "危险性类别", "hazard_class", "hazardclass",
    "위험 등급", "hazard classifications")
_reg("Storage class", "存储类别", "ストレージクラス", "스토리지 클래스", "storage class",
    "speicherklasse")
_reg("Safety statements (S)", "安全说明", "safety_code", "safety statements")
_reg("Risk statements (R)", "危险类别码", "risk_code", "risk statements")
_reg("Hazard symbols", "危险品标志", "hazard_code", "hazard codes", "危险性符号(ghs)")
_reg("Customs code", "海关编码", "hs_code", "hs 번호", "hs code")
_reg("Toxicity", "毒性", "독성", "toxizität", "toxicity")
_reg("Hazardous substances data", "毒害物质数据", "有毒物質データの",
    "giftige stoffe daten", "유해 물질 데이터", "hazardous substances data")
_reg("Occupational exposure band (OEB)", "职业暴露等级", "oeb")
_reg("Occupational exposure limit (OEL)", "职业暴露限值", "oel")
_reg("Immediately dangerous to life or health", "立即威胁生命和健康浓度", "idla", "idlh")
_reg("GHS signal word", "signal word", "信号词", "alarmwort", "注意喚起語",
    "신호 어", "警示词")
_reg("GHS hazard statements", "hazard statements", "gefahrenhinweise",
    "危険有害性情報", "유해·위험 문구", "危险性描述")
_reg("GHS precautionary statements", "precautionary statements", "防范说明")
_reg("GHS pictogram", "symbol(ghs)")
_reg("GHS classification", "ghs classification")
_reg("REACH registrations", "reach registrations", "reach 注册登记")
_reg("Personal protective equipment (PPE)", "ppe")
_reg("Exposure limits", "暴露限值", "exposure limits")
_reg("Hazard note", "hazard_note", "hazard note", "위험 참고 사항")


def field_label(raw: str) -> str:
    """原始标签 → 规范英文字段名; 未收录原样返回。"""
    return _CANONICAL.get(raw.strip().lower(), raw)


def field_key(raw: str) -> str:
    """去重键: 规范字段名(小写); 未收录时为规范化原标签。"""
    return field_label(raw).strip().lower()
