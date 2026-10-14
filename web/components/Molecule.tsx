"use client";

/**
 * Molecule — 化合物结构图（RDKit SVG 端点渲染）。
 *
 * locale 来源: I18nContext(runtime locale); alt / noStructureText 仍可显式覆盖。
 * 结构图加载失败或无结构时显示占位（图标 24 + 暂无结构图，DESIGN_SYSTEM 5.1），
 * 不露 alt 文本。
 */
import { useState } from "react";
import { molSvgUrl, MOL_SVG_SIZES, type MolSvgSizeKey } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { GlyphChem } from "@/components/ui/icons";

export function Molecule({
  chemicalId,
  smiles,
  label,
  size = "lg",
  width,
  height,
  alt,
  noStructureText,
}: {
  chemicalId: number;
  smiles?: string | null;
  label?: string | null;
  /** 标准尺寸档位（lg 280×210, md 160×120, sm 112×84, xs 64×48） */
  size?: MolSvgSizeKey;
  width?: number;
  height?: number;
  /** 覆盖默认 alt；未传用当前字典 structureAlt */
  alt?: string;
  /** 覆盖「无结构」占位文案；未传用当前字典 noStructure */
  noStructureText?: string;
}) {
  const t = useDictionary();
  const [loadError, setLoadError] = useState(false);
  const placeholderText = noStructureText ?? t.chemical.noStructure;

  if (!chemicalId || smiles === null || smiles === "" || loadError) {
    return (
      <span className="mol-placeholder" aria-label={placeholderText}>
        <GlyphChem width={24} height={24} aria-hidden="true" />
        <span>{placeholderText}</span>
      </span>
    );
  }
  const name = label || t.common.hcidShort(chemicalId);
  // SVG is rendered by our validated RDKit endpoint; no remote image host is involved.
  // alt="" prevents the browser from displaying broken alt text if the image fails;
  // aria-label preserves accessibility.
  // eslint-disable-next-line @next/next/no-img-element
  const dim = MOL_SVG_SIZES[size];
  const w = width ?? dim.width;
  const h = height ?? dim.height;
  return (
    <img
      src={molSvgUrl(chemicalId, w, h)}
      width={w}
      height={h}
      alt=""
      role="img"
      aria-label={alt ?? t.chemical.structureAlt(name)}
      loading="lazy"
      onError={() => setLoadError(true)}
    />
  );
}
