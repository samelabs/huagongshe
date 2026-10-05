"use client";

/**
 * Molecule — 化合物结构图（RDKit SVG 端点渲染）。
 *
 * locale 来源: I18nContext(runtime locale); alt / noStructureText 仍可显式覆盖。
 * 公开调用方(Search/Chemical/Reaction)均已传 alt, 默认值仅兜底无 Provider 场景
 * (不存在于当前 app —— root layout 恒包 I18nProvider)。
 */
import { molSvgUrl } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";

export function Molecule({ chemicalId, smiles, label, width = 260, height = 180, alt, noStructureText }: {
  chemicalId: number;
  smiles?: string | null;
  label?: string | null;
  width?: number;
  height?: number;
  /** 覆盖默认 alt；未传用当前字典 structureAlt */
  alt?: string;
  /** 覆盖「无结构」占位文案；未传用当前字典 noStructure */
  noStructureText?: string;
}) {
  const t = useDictionary();
  if (!chemicalId) return <span className="result-sub">{noStructureText ?? t.reaction.noStructure}</span>;
  const name = label || `HCID ${chemicalId}`;
  // SVG is rendered by our validated RDKit endpoint; no remote image host is involved.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={molSvgUrl(chemicalId, width, height)} width={width} height={height} alt={alt ?? t.chemical.structureAlt(name)} loading="lazy" />;
}
