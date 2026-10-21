/**
 * reactionTitle — 反应标题的唯一解析（详情页 H1 与列表卡标题共用）。
 *
 * 规则：主反应物取第一个反应物；主产物取有收率中最高的一个，都没有
 * 收率时取第一个产物。名称解析走 resolveChemicalName 同一条链的叙述
 * 形态（preferCas: false —— 反应标题是名称叙事，CAS 号成对不可读）。
 */
import { resolveChemicalName } from "@/lib/chemicalName";
import type { Chemical } from "@/lib/api";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import type { Locale } from "@/lib/i18n/locales";

/** 参与物带角色与收率的投影（详情接口与用户主页列表接口同形状） */
export type TitledParticipant = Chemical & {
  role?: string | null;
  yield_percent?: number | null;
};

export function reactionTitleText(
  participants: TitledParticipant[],
  opts: { t: Dictionary; locale: Locale; reactionId: number | string },
): string {
  const reactants = participants.filter((item) => item.role === "REACTANT");
  const products = participants.filter((item) => item.role === "PRODUCT");
  const productsWithYield = products.filter(
    (p) => typeof p.yield_percent === "number" && !isNaN(p.yield_percent),
  );
  const primaryReactant = reactants[0];
  const primaryProduct = productsWithYield.length > 0
    ? productsWithYield.reduce((max, cur) => ((cur.yield_percent ?? 0) > (max.yield_percent ?? 0) ? cur : max))
    : products[0];
  const left = primaryReactant
    ? resolveChemicalName(primaryReactant, opts.t.common.hcidLabel, opts.locale, { preferCas: false }).title
    : "";
  const right = primaryProduct
    ? resolveChemicalName(primaryProduct, opts.t.common.hcidLabel, opts.locale, { preferCas: false }).title
    : "";
  if (left && right) return opts.t.reaction.reactionTitle(left, right);
  if (left) return `${left} →`;
  if (right) return `→ ${right}`;
  return opts.t.reaction.reactionTitleFallback(opts.reactionId);
}
