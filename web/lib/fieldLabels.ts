/**
 * 化合物性质与安全字段的五语言名称字典。
 *
 * 数据里的字段标签有多种形态：规范代码（wgk、tsca）、按请求语言本地化的
 * 名称（熔点 / 融点 / Melting point / 녹는점 / Schmelzpunkt）、以及段落
 * 路径的最后一段（Experimental Properties > pH → pH）。同一字段在不同
 * 语言下标签不同，展示时统一映射为规范字段并按当前语言取名；未收录的
 * 标签原样保留（多为专有名词，本身已是当前语言）。
 */

export type FieldLocale = "zh-CN" | "ja" | "ko" | "de" | "en";

type FieldDef = {
  key: string;
  labels: Record<FieldLocale, string>;
  /** 参与匹配的原始标签（小写比较）。 */
  match: string[];
};

const F = (
  key: string,
  zh: string,
  ja: string,
  ko: string,
  de: string,
  en: string,
  ...match: string[]
): FieldDef => ({
  key,
  labels: { "zh-CN": zh, ja, ko, de, en },
  match: [key, ...match].map((m) => m.toLowerCase()),
});

/** 性质字段（物理/化学）。 */
export const PROPERTY_FIELDS: FieldDef[] = [
  F("melting_point", "熔点", "融点", "녹는점", "Schmelzpunkt", "Melting point",
    "熔点", "融点", "melting point", "녹는점", "schmelzpunkt"),
  F("freezing_point", "凝固点", "凝固点", "어는점", "Gefrierpunkt", "Freezing point",
    "凝固点", "freezingpoint", "freezing point"),
  F("boiling_point", "沸点", "沸点", "끓는 점", "Siedepunkt", "Boiling point",
    "沸点", "boiling point", "끓는 점", "siedepunkt"),
  F("density", "密度", "密度", "밀도", "Dichte", "Density",
    "密度", "比重(密度)", "density", "밀도", "dichte"),
  F("bulk_density", "堆积密度", "かさ密度", "벌크 밀도", "Schüttdichte", "Bulk density",
    "堆积密度", "bulk density", "かさ密度"),
  F("specific_gravity", "比重", "比重", "비중", "Wichte", "Specific gravity",
    "比重", "specific gravity", "wichte"),
  F("vapor_pressure", "蒸气压", "蒸気圧", "증기압", "Dampfdruck", "Vapor pressure",
    "蒸气压", "蒸気圧", "vapor pressure", "증기압", "dampfdruck"),
  F("vapor_density", "蒸气密度", "蒸気密度", "증기 밀도", "Dampfdichte", "Vapor density",
    "蒸气密度", "蒸気密度", "vapor density", "증기 밀도", "dampfdichte"),
  F("refractive_index", "折射率", "屈折率", "굴절률", "Brechungsindex", "Refractive index",
    "折射率", "屈折率", "refractive index", "굴절률", "brechungsindex"),
  F("flash_point", "闪点", "引火点", "인화점", "Flammpunkt", "Flash point",
    "闪点", "引火点", "flash point", "인화점", "flammpunkt"),
  F("ph", "pH", "pH", "pH", "pH", "pH", "ph", "ph值", "수소이온지수(ph)"),
  F("logp", "LogP（油水分配系数）", "LogP（分配係数）", "LogP(분배 계수)", "LogP (Verteilungskoeffizient)", "LogP (partition coefficient)", "logp"),
  F("pka", "pKa（酸度系数）", "pKa（酸解離定数）", "pKa(산도 계수)", "pKa (Säurekonstante)", "pKa (acidity coefficient)",
    "pka", "酸度系数(pka)", "酸解離定数(pka)", "산도 계수 (pka)"),
  F("solubility", "溶解性", "溶解度", "용해도", "Löslichkeit", "Solubility",
    "溶解度", "溶解性", "水溶解度", "水溶解性", "solubility", "수용성", "löslichkeit", "wasserlöslichkeit", "water solubility"),
  F("odor", "气味", "臭い", "냄새", "Geruch", "Odor",
    "气味 (odor)", "臭い (odor)", "냄새", "geruch (odor)", "odor", "气味", "臭い"),
  F("odor_type", "香型", "香りのタイプ", "향취 유형", "Geruchsart", "Odor type",
    "香型", "臭いのタイプ", "냄새 유형", "geruchsart", "odor type"),
  F("odor_threshold", "嗅觉阈值", "臭気閾値", "후각 역치", "Geruchsschwelle", "Odor threshold",
    "嗅觉阈值(odor threshold)", "臭気閾値(odor threshold)", "geruchsschwelle", "odor threshold"),
  F("taste", "味道", "味", "맛", "Geschmack", "Taste", "味道", "taste"),
  F("color", "颜色", "色", "색상", "Farbe", "Color", "颜色", "色", "색상", "farbe", "color"),
  F("physical_state", "形态", "外観・状態", "물리적 상태", "Aggregatzustand", "Physical state",
    "形态", "外見", "物리적 상태", "aggregatzustand", "form"),
  F("storage_conditions", "储存条件", "貯蔵条件", "저장 조건", "Lagerbedingungen", "Storage conditions",
    "储存条件", "貯蔵温度", "저장 조건", "storage temp.", "貯蔵温度"),
  F("stability", "稳定性", "安定性", "안정성", "Stabilität", "Stability",
    "稳定性", "安定性", "안정성", "stability", "stabilität"),
  F("sensitivity", "敏感性", "感度", "감도", "Empfindlichkeit", "Sensitivity",
    "敏感性", "sensitive", "empfindlichkeit", "sensitivity"),
  F("auto_ignition_temperature", "自燃温度", "自然発火温度", "자연 발화 온도", "Selbstentzündungstemperatur", "Autoignition temperature",
    "自燃温度", "自然発火温度", "자연 발화 온도", "selbstentzündungstemperatur", "autoignition temperature"),
  F("explosive_limits", "爆炸极限", "爆発限界", "폭발한계", "Explosionsgrenze", "Explosive limits",
    "爆炸极限值(explosive limit)", "爆発限界(explosive limit)", "폭발한계", "explosionsgrenze", "explosive limit"),
  F("dielectric_constant", "介电常数", "誘電率", "유전율", "Dielektrizitätskonstante", "Dielectric constant",
    "介电常数", "dielectric constant", "dielektrizitätskonstante"),
  F("specific_heat", "比热容", "比熱容量", "비열", "Spezifische Wärmekapazität", "Specific heat capacity",
    "比热容", "比熱容量", "비열", "spezifische wärmekapazität", "specific heat capacity"),
  F("thermal_conductivity", "热导率", "熱伝導率", "열전도율", "Wärmeleitfähigkeit", "Thermal conductivity",
    "热导率", "thermal conductivity", "wärmeleitfähigkeit"),
  F("henrys_law_constant", "亨利常数", "ヘンリー定数", "헨리 상수", "Henry-Konstante", "Henry's law constant",
    "henry's law constant", "헨리 상수", "henry-konstante", "亨利常数"),
  F("major_applications", "主要应用", "主な用途", "주요 응용", "Hauptanwendungen", "Major applications",
    "主要应用", "主な用途", "주요 응용", "major application"),
  F("biological_source", "生物来源", "由来生物", "생물학적 소스", "Biologische Quelle", "Biological source",
    "生物来源", "由来生物", "생물학적 소스", "biological source", "biologische quelle"),
  F("xlogp", "XLogP", "XLogP", "XLogP", "XLogP", "XLogP", "xlogp"),
];

/** 安全与法规字段。 */
export const SAFETY_FIELDS: FieldDef[] = [
  F("water_hazard_class", "水危害等级（WGK）", "水環境危害等級（WGK）", "수질 위해 등급(WGK)", "Wassergefährdungsklasse (WGK)", "Water hazard class (WGK)",
    "wgk", "wgk germany"),
  F("tsca_status", "TSCA 清单状态", "TSCA 収載状態", "TSCA 등재 상태", "TSCA-Inventar-Status", "TSCA inventory status",
    "tsca"),
  F("rtecs_number", "RTECS 号", "RTECS 番号", "RTECS 번호", "RTECS-Nr.", "RTECS number",
    "rtecs", "rtecs号", "rtecs-nr."),
  F("un_transport_number", "运输编号（UN）", "輸送番号（UN）", "운송 번호(UN)", "UN-Transportnummer", "UN transport number",
    "ridadr", "危险品运输编号"),
  F("packing_group", "包装类别", "包装等級", "포장분류", "Verpackungsgruppe", "Packing group",
    "包装类别", "packinggroup", "packing_group", "포장분류", "verpackungsgruppe"),
  F("hazard_class", "危险类别", "危険等級", "위험 등급", "Gefahrenklasse", "Hazard class",
    "危险等级", "危险性类别", "hazard_class", "hazardclass", "위험 등급", "hazard classifications", "gefahrenklasse"),
  F("storage_class", "储存类别", "貯蔵分類", "저장 분류", "Lagerklasse", "Storage class",
    "存储类别", "ストレージクラス", "스토리지 클래스", "storage class", "speicherklasse", "lagerklasse"),
  F("safety_statements", "安全说明（S）", "安全措置（S）", "안전 문구(S)", "Sicherheitshinweise (S)", "Safety statements (S)",
    "安全说明", "safety_code", "safety statements"),
  F("risk_statements", "危险类别码（R）", "危険文句（R）", "위험 문구(R)", "R-Sätze (R)", "Risk statements (R)",
    "危险类别码", "risk_code", "risk statements"),
  F("hazard_symbols", "危险品标志", "危険表示", "위험 표시", "Gefahrensymbole", "Hazard symbols",
    "危险品标志", "hazard_code", "hazard codes"),
  F("customs_code", "海关编码", "税関コード", "관세 코드", "Zollcode", "Customs code",
    "海关编码", "hs_code", "hs 번호", "hs code"),
  F("toxicity", "毒性", "毒性", "독성", "Toxizität", "Toxicity",
    "毒性", "독성", "toxizität", "toxicity"),
  F("hazardous_substances_data", "毒害物质数据", "有害物質データ", "유해 물질 데이터", "Gefahrstoffdaten", "Hazardous substances data",
    "毒害物质数据", "有毒物質データの", "giftige stoffe daten", "유해 물질 데이터", "hazardous substances data"),
  F("occupational_exposure_band", "职业暴露等级（OEB）", "職業暴露区分（OEB）", "직업 노출 등급(OEB)", "Berufliche Expositionsstufe (OEB)", "Occupational exposure band (OEB)",
    "职业暴露等级", "oeb"),
  F("occupational_exposure_limit", "职业暴露限值（OEL）", "職業暴露限界（OEL）", "직업 노출 한계(OEL)", "Arbeitsplatzgrenzwert (OEL)", "Occupational exposure limit (OEL)",
    "职业暴露限值", "oel"),
  F("idlh", "立即危及生命和健康浓度", "生命健康即時危険濃度", "즉시 생명 위험 농도", "Sofort lebensgefährliche Konzentration", "Immediately dangerous to life or health concentration",
    "立即威胁生命和健康浓度", "idla", "idlh"),
  F("ghs_classification", "GHS 分类", "GHS 分類", "GHS 분류", "GHS-Einstufung", "GHS classification",
    "ghs_classification", "ghs classification"),
  F("ghs_signal_word", "信号词", "信号語", "신호어", "Signalwort", "Signal word", "signal word"),
  F("ghs_hazard_statements", "危险性说明（GHS）", "有害性文書（GHS）", "유해성 문구(GHS)", "GHS-Gefahrenhinweise", "GHS hazard statements",
    "hazard statements"),
  F("ghs_precautionary_statements", "防范说明（GHS）", "注意文書（GHS）", "예방조치 문구(GHS)", "GHS-Sicherheitshinweise", "GHS precautionary statements",
    "precautionary statements"),
  F("ghs_pictogram", "GHS 象形图", "GHS 絵表示", "GHS 픽토그램", "GHS-Piktogramm", "GHS pictogram",
    "symbol(ghs)"),
  F("reach_registrations", "REACH 注册", "REACH 登録", "REACH 등록", "REACH-Registrierungen", "REACH registrations",
    "reach registrations"),
  F("ppe", "个人防护装备（PPE）", "個人防護具（PPE）", "개인 보호구(PPE)", "Persönliche Schutzausrüstung (PPE)", "Personal protective equipment (PPE)",
    "ppe"),
  F("limited_quantities", "有限数量", "数量制限", "제한 수량", "Begrenzte Mengen", "Limited quantities", "limited quantities"),
  F("excepted_quantities", "例外数量", "例外数量", "예외 수량", "Ausnahmemengen", "Excepted quantities", "excepted quantities"),
  F("exposure_limits", "暴露限值", "暴露限界", "노출 한계", "Expositionsgrenzen", "Exposure limits",
    "暴露限值", "exposure limits"),
];

/** 证据段落标题（危害/防护/毒理/法规段落的最后一段）。 */
export const SECTION_HEADING_FIELDS: FieldDef[] = [
  F("hazards_summary", "危害概述", "有害性の概要", "유해성 요약", "Gefahrenübersicht", "Hazards summary", "hazards summary"),
  F("health_hazards", "健康危害", "健康有害性", "건강 유해성", "Gesundheitsgefahren", "Health hazards", "health hazards"),
  F("health_effects", "健康影响", "健康影響", "건강 영향", "Gesundheitliche Auswirkungen", "Health effects", "health effects"),
  F("fire_hazards", "火灾危害", "火災危険", "화재 위험", "Brandgefahren", "Fire hazards", "fire hazards"),
  F("fire_potential", "火灾可能性", "火災の可能性", "화재 가능성", "Brandpotenzial", "Fire potential", "fire potential"),
  F("fire_fighting", "消防", "消火", "소화", "Brandbekämpfung", "Fire fighting", "fire fighting"),
  F("fire_fighting_procedures", "灭火程序", "消火手順", "소화 절차", "Brandbekämpfungsverfahren", "Fire fighting procedures", "fire fighting procedures"),
  F("first_aid", "急救", "応急処置", "응급 처치", "Erste Hilfe", "First aid", "first aid"),
  F("first_aid_measures", "急救措施", "応急処置措置", "응급 조치", "Erste-Hilfe-Maßnahmen", "First aid measures", "first aid measures"),
  F("cleanup_methods", "清理方法", "清掃方法", "정리 방법", "Reinigungsverfahren", "Cleanup methods", "cleanup methods"),
  F("disposal_methods", "处置方法", "処分方法", "처리 방법", "Entsorgungsverfahren", "Disposal methods", "disposal methods"),
  F("spillage_disposal", "泄漏处置", "漏出処分", "누출 처리", "Verschüttetes entsorgen", "Spillage disposal", "spillage disposal"),
  F("nonfire_spill_response", "非火灾泄漏应对", "非火災時の漏出対応", "비화재 누출 대응", "Freisetung ohne Brand", "Nonfire spill response", "nonfire spill response"),
  F("safe_storage", "安全储存", "安全保管", "안전 보관", "Sichere Lagerung", "Safe storage", "safe storage"),
  F("storage_conditions", "储存条件", "保管条件", "보관 조건", "Lagerbedingungen", "Storage conditions", "storage conditions"),
  F("exposure_control_ppp", "暴露控制与个人防护", "暴露管理・個人防護", "노출 관리 및 개인 보호", "Expositionsschutz und Persönliche Schutzausrüstung", "Exposure control and personal protection", "exposure control and personal protection"),
  F("reactive_group", "反应性基团", "反応性グループ", "반응성 그룹", "Reaktive Gruppe", "Reactive group", "reactive group"),
  F("target_organs", "靶器官", "標的器官", "표적 장기", "Zielorgane", "Target organs", "target organs"),
  F("adverse_effects", "不良影响", "有害作用", "유해 작용", "Unerwünschte Wirkungen", "Adverse effects", "adverse effects"),
  F("interactions", "相互作用", "相互作用", "상호 작용", "Wechselwirkungen", "Interactions", "interactions"),
  F("exposure_routes", "暴露途径", "暴露経路", "노출 경로", "Expositionspfade", "Exposure routes", "exposure routes"),
  F("toxicity_summary", "毒性概述", "毒性の概要", "독성 요약", "Toxizitätsübersicht", "Toxicity summary", "toxicity summary"),
  F("toxicological_information", "毒理学资料", "毒性学的情報", "독성학 정보", "Toxikologische Informationen", "Toxicological information", "toxicological information"),
  F("ecotoxicity_values", "生态毒性数值", "生態毒性値", "생태독성 수치", "Ökotoxizitätswerte", "Ecotoxicity values", "ecotoxicity values"),
  F("ecotoxicity_excerpts", "生态毒性摘录", "生態毒性抜粋", "생태독성 발췌", "Ökotoxizitätsauszüge", "Ecotoxicity excerpts", "ecotoxicity excerpts"),
  F("environmental_fate", "环境归趋", "環境中動態", "환경 거동", "Umweltverhalten", "Environmental fate", "environmental fate"),
  F("body_burden", "体内负荷", "体内負荷", "체내 부담", "Körperbelastung", "Body burden", "body burden"),
  F("food_survey_values", "食品调查数值", "食品調査値", "식품 조사 수치", "Lebensmitteluntersuchungswerte", "Food survey values", "food survey values"),
  F("regulatory_information", "法规信息", "規制情報", "규제 정보", "Regulatorische Informationen", "Regulatory information", "regulatory information"),
  F("other_safety_information", "其他安全信息", "その他の安全情報", "기타 안전 정보", "Weitere Sicherheitsinformationen", "Other safety information", "other safety information"),
  F("dot_label", "运输标签（DOT）", "輸送ラベル（DOT）", "운송 라벨(DOT)", "DOT-Kennzeichnung", "DOT label", "dot label"),
  F("dot_id_guide", "运输编号与指南（DOT）", "輸送番号・ガイド（DOT）", "운송 번호 및 가이드(DOT)", "DOT-Nummer und Handbuch", "DOT ID and guide", "dot id and guide"),
  F("ec_classification", "欧共体分类", "EC 分類", "EC 분류", "EG-Einstufung", "EC classification", "ec classification"),
  F("un_classification", "联合国分类", "UN 分類", "UN 분류", "UN-Einstufung", "UN classification", "un classification"),
  F("fda_requirements", "FDA 要求", "FDA 要件", "FDA 요건", "FDA-Anforderungen", "FDA requirements", "fda requirements"),
  F("tsca_requirements", "TSCA 要求", "TSCA 要件", "TSCA 요건", "TSCA-Anforderungen", "TSCA requirements", "tsca requirements"),
  F("fifra_requirements", "FIFRA 要求", "FIFRA 要件", "FIFRA 요건", "FIFRA-Anforderungen", "FIFRA requirements", "fifra requirements"),
  F("rcra_requirements", "RCRA 要求", "RCRA 要件", "RCRA 요건", "RCRA-Anforderungen", "RCRA requirements", "rcra requirements"),
  F("cercla_reportable_quantities", "CERCLA 应报告数量", "CERCLA 報告数量", "CERCLA 보고 수량", "CERCLA-Meldepflichtmengen", "CERCLA reportable quantities", "cercla reportable quantities"),
  F("clean_water_act_requirements", "清洁水法要求", "清浄水法要件", "청정수법 요건", "Clean Water Act Anforderungen", "Clean Water Act requirements", "clean water act requirements"),
  F("atmospheric_standards", "大气标准", "大気基準", "대기 기준", "Luftstandards", "Atmospheric standards", "atmospheric standards"),
  F("federal_drinking_water_guidelines", "联邦饮用水指南", "連邦飲料水ガイドライン", "연방 식수 지침", "Bundesrichtlinien für Trinkwasser", "Federal drinking water guidelines", "federal drinking water guidelines"),
  F("state_drinking_water_guidelines", "州饮用水指南", "州飲料水ガイドライン", "주 식수 지침", "Landesrichtlinien für Trinkwasser", "State drinking water guidelines", "state drinking water guidelines"),
  F("accidental_release_measures", "泄漏应急措施", "漏出応急措置", "누출 비상 조치", "Freisetungsmaßnahmen", "Accidental release measures", "accidental release measures"),
];

/** 物质类别（Chemical Classes 的子类）。 */
export const CLASS_FIELDS: FieldDef[] = [
  F("chemical_classes", "物质类别", "物質分類", "물질 분류", "Stoffklassen", "Chemical classes", "chemical classes"),
  F("class_drugs", "药物", "医薬品", "의약품", "Arzneimittel", "Drugs", "drugs"),
  F("class_cosmetics", "化妆品", "化粧品", "화장품", "Kosmetika", "Cosmetics", "cosmetics"),
  F("class_fragrances", "香料", "香料", "향료", "Duftstoffe", "Fragrances", "fragrances"),
  F("class_pesticides", "农药", "農薬", "농약", "Pestizide", "Pesticides", "pesticides"),
  F("class_food_additives", "食品添加剂", "食品添加物", "식품 첨가물", "Lebensmittelzusatzstoffe", "Food additives", "food additives"),
  F("class_flavoring_agents", "食用香料", "香味料", "향미제", "Aromastoffe", "Flavoring agents", "flavoring agents"),
  F("class_lipids", "脂质", "脂質", "지질", "Lipide", "Lipids", "lipids"),
];

const ALL_FIELDS: FieldDef[] = [
  ...PROPERTY_FIELDS, ...SAFETY_FIELDS, ...SECTION_HEADING_FIELDS, ...CLASS_FIELDS,
];

const LOOKUP = new Map<string, FieldDef>();
for (const field of ALL_FIELDS) {
  for (const token of field.match) {
    if (!LOOKUP.has(token)) LOOKUP.set(token, field);
  }
}

function normalize(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, " ");
}

/** 原始标签 → 规范字段（未收录返回 null）。 */
export function fieldByKey(key: string): FieldDef | null {
  return LOOKUP.get(key) ?? null;
}

/** 原始标签 → 当前语言的字段名；未收录的标签原样返回。 */
export function fieldLabel(raw: string, locale: FieldLocale): string {
  const field = LOOKUP.get(normalize(raw));
  return field ? field.labels[locale] : raw;
}

/** 原始标签 → 规范字段键（用于同一字段去重）；未收录时用规范化原标签。 */
export function fieldKey(raw: string): string {
  const field = LOOKUP.get(normalize(raw));
  return field ? field.key : normalize(raw);
}

/** 段落路径（A > B > C）的展示名：逐段映射，未映射的段保留原文。 */
export function pathLabel(path: string, locale: FieldLocale): string {
  const segments = path.split(" > ");
  const last = segments[segments.length - 1] || path;
  return fieldLabel(last, locale);
}
