/**
 * 化合物显示名称 · 全站唯一解析规则 (single resolver)
 *
 * 为什么存在: 详情页 H1、搜索结果主标题、SEO metadata(<title>/OG/JSON-LD)、
 * 分享标题、工作台列表此前各自维护一套 fallback(且互不一致)。此模块是唯一
 * 规则出口 —— 任何展示化合物名称的地方都必须消费本函数结果, 不允许再写
 * `preferred_name || iupac_name || ...` 之类的第二套链。
 *
 * 规则(2026-10-21 裁定: CAS 优先、分子式不进标题; 与数据源一一对应):
 *   身份链(默认, preferCas 省略):
 *     CAS 号               ← chemistry.chemicals.cas / cas_numbers[0]
 *     → 当前 locale 常用名 ← name_index kind='name_cn' (镜像 CB identity.cn, 汉语)
 *     → English 常用名     ← chemistry.chemicals.preferred_name (PubChem Title / CB identity.en)
 *     → 系统名(IUPAC)      ← chemistry.chemicals.iupac_name (PubChem IUPACName)
 *     → HCID {id}          ← i18n 现有标签 t.common.hcidLabel(新建行/无数据行)
 *   叙述链(preferCas: false —— 仅反应标题这类以名称叙事的场合):
 *     常用名 → IUPAC → CAS → HCID。
 *   分子式从链中移除 —— 标题场景不显式表达(详情属性表照常展示)。
 *
 * secondary(结合场景):
 *   主标题是 CAS/HCID 时给出首个可用名称(本地名→英文→IUPAC)作人类可读
 *   伴随; 主标题是本地化名称时给出英文常用名(缺则 IUPAC 兜底);
 *   与主标题同串(忽略大小写)不展示。
 *
 * locale: 公开详情页按 runtime locale 传参调用 resolveChemicalName;
 *         SITE_LOCALE(web/lib/locale.ts)仍是 formatter 类常量的单一来源。
 */

import { SITE_LOCALE } from "./locale";

// 向后兼容再导出: 此前 SITE_LOCALE 定义在本文件, 保留导出避免调用方断裂。
export { SITE_LOCALE };

export type ChemicalNameFields = {
  id: number | string;
  name_local?: string | null;
  name_cn?: string | null;
  preferred_name?: string | null;
  iupac_name?: string | null;
  molecular_formula?: string | null;
  cas_numbers?: string[] | null;
  cas?: string | null;
};

export type ChemicalNameSource =
  | "name_local"
  | "name_cn"
  | "preferred_name"
  | "iupac_name"
  | "cas"
  | "hcid";

export type ResolvedChemicalName = {
  title: string;
  secondary: string | null;
  source: ChemicalNameSource;
};

function clean(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  return text ? text : null;
}

export function isChineseLocale(locale: string): boolean {
  return /^zh\b/i.test((locale ?? "").trim());
}

export function resolveChemicalName(
  chemical: ChemicalNameFields,
  hcidLabel: (id: number | string) => string,
  locale: string = SITE_LOCALE,
  opts?: { preferCas?: boolean },
): ResolvedChemicalName {
  const preferCas = opts?.preferCas !== false;
  const localVal = clean(chemical.name_local) ?? (isChineseLocale(locale) ? clean(chemical.name_cn) : null);
  const common = clean(chemical.preferred_name);
  const systematic = clean(chemical.iupac_name);
  const casVal = clean(chemical.cas ?? chemical.cas_numbers?.[0]);

  const localSource: ChemicalNameSource = clean(chemical.name_local) ? "name_local" : "name_cn";

  const identityChain: [string | null, ChemicalNameSource][] = [
    [casVal, "cas"],
    [localVal, localSource],
    [common, "preferred_name"],
    [systematic, "iupac_name"],
  ];
  const narrativeChain: [string | null, ChemicalNameSource][] = [
    [localVal, localSource],
    [common, "preferred_name"],
    [systematic, "iupac_name"],
    [casVal, "cas"],
  ];

  const hit = (preferCas ? identityChain : narrativeChain).find(([value]) => value !== null);
  const source: ChemicalNameSource = hit ? hit[1] : "hcid";
  const title = hit ? (hit[0] as string) : hcidLabel(chemical.id);

  const isLocalSource = source === "name_local" || source === "name_cn";
  // 副标题: 本地化主标题 → 英文常用名(缺则 IUPAC); CAS/HCID 主标题 →
  // 首个可用名称作可读伴随; 同串(忽略大小写)不展示。
  const subtitleCandidate = isLocalSource
    ? (common ?? systematic)
    : (localVal ?? common ?? systematic);
  const secondary = (isLocalSource || source === "cas" || source === "hcid") && subtitleCandidate
    && subtitleCandidate.toLowerCase() !== title.toLowerCase()
    ? subtitleCandidate
    : null;

  return { title, secondary, source };
}
