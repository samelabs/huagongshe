/**
 * 化合物显示名称 · 全站唯一解析规则 (single resolver)
 *
 * 为什么存在: 详情页 H1、搜索结果主标题、SEO metadata(<title>/OG/JSON-LD)、
 * 分享标题、工作台列表此前各自维护一套 fallback(且互不一致)。此模块是唯一
 * 规则出口 —— 任何展示化合物名称的地方都必须消费本函数结果, 不允许再写
 * `preferred_name || iupac_name || ...` 之类的第二套链。
 *
 * 规则(与数据源一一对应, 不猜、不翻译、不由 CAS/SMILES 推导):
 *   当前 locale 的常用名  ← chemistry.name_index kind='name_cn' (镜像 chemical_cb.identity.cn, 汉语)
 *   → English 常用名       ← chemistry.chemicals.preferred_name (PubChem Title / CB identity.en)
 *   → 系统名(IUPAC)        ← chemistry.chemicals.iupac_name (PubChem IUPACName)
 *   → 分子式               ← chemistry.chemicals.molecular_formula
 *   → HCID {id}            ← i18n 现有标签 t.common.hcidLabel
 *
 * secondary: 主标题是本地化名称且存在不同的英文常用名时给出英文名;
 *            主标题本身已是英文名时不重复展示。
 *
 * locale: 公开详情页按 runtime locale 传参调用 resolveChemicalName;
 *         SITE_LOCALE(web/lib/locale.ts)仍是 formatter 类常量的单一来源。
 */

import { SITE_LOCALE } from "./locale";

// 向后兼容再导出: 此前 SITE_LOCALE 定义在本文件, 保留导出避免调用方断裂。
export { SITE_LOCALE };

export type ChemicalNameFields = {
  id: number | string;
  name_cn?: string | null;
  preferred_name?: string | null;
  iupac_name?: string | null;
  molecular_formula?: string | null;
};

export type ChemicalNameSource =
  | "name_cn"
  | "preferred_name"
  | "iupac_name"
  | "molecular_formula"
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
): ResolvedChemicalName {
  const localized = clean(chemical.name_cn);
  const common = clean(chemical.preferred_name);
  const systematic = clean(chemical.iupac_name);
  const formula = clean(chemical.molecular_formula);

  const chain: [string | null, ChemicalNameSource][] = isChineseLocale(locale)
    ? [[localized, "name_cn"], [common, "preferred_name"], [systematic, "iupac_name"], [formula, "molecular_formula"]]
    : [[common, "preferred_name"], [systematic, "iupac_name"], [formula, "molecular_formula"]];

  const hit = chain.find(([value]) => value !== null);
  const source: ChemicalNameSource = hit ? hit[1] : "hcid";
  const title = hit ? (hit[0] as string) : hcidLabel(chemical.id);

  const secondary = source === "name_cn" && common && common.toLowerCase() !== title.toLowerCase()
    ? common
    : null;

  return { title, secondary, source };
}
