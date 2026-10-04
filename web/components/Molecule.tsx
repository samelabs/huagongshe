import { molSvgUrl } from "@/lib/api";
import t from "@/lib/i18n";

/**
 * Molecule — 化合物结构图（RDKit SVG 端点渲染）。
 *
 * alt / noStructure 默认保持静态 zh（chemical/reaction 详情页等调用方零行为变化）;
 * 已迁移 runtime locale 的调用方（Search 结果卡）通过 alt / noStructureText
 * 传入当前请求语言文案。Search 链全部迁移后, 默认值再统一切换来源。
 */
export function Molecule({ chemicalId, smiles, label, width = 260, height = 180, alt, noStructureText }: {
  chemicalId: number;
  smiles?: string | null;
  label?: string | null;
  width?: number;
  height?: number;
  /** 覆盖默认 alt（`${name} 分子结构式`）；未传保持中文默认 */
  alt?: string;
  /** 覆盖默认「无结构」占位文案；未传保持中文默认 */
  noStructureText?: string;
}) {
  if (!chemicalId) return <span className="result-sub">{noStructureText ?? t.reaction.noStructure}</span>;
  const name = label || `HCID ${chemicalId}`;
  // SVG is rendered by our validated RDKit endpoint; no remote image host is involved.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={molSvgUrl(chemicalId, width, height)} width={width} height={height} alt={alt ?? `${name} 分子结构式`} loading="lazy" />;
}
