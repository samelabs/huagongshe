"use client";

/**
 * Molecule — 化合物结构图（RDKit SVG 端点渲染）。
 *
 * 图地址不带尺寸（矢量图），显示尺寸由容器 CSS 决定；width/height 属性
 * 只是 4:3 宽高比提示，避免加载期间布局跳动。
 * locale 来源: I18nContext(runtime locale); alt / noStructureText 仍可显式覆盖。
 * 结构图加载失败或无结构时显示占位（图标 24 + 暂无结构图），不露 alt 文本。
 */
import { useState } from "react";
import { molSvgUrl } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { GlyphChem } from "@/components/ui/icons";

/** 展示宽高比提示档位（仅作 img 属性提示，不进图地址） */
const MOL_ASPECT_HINTS = {
  lg: { width: 280, height: 210 },
  md: { width: 160, height: 120 },
  sm: { width: 112, height: 84 },
  xs: { width: 64, height: 48 },
} as const;

export type MolSizeKey = keyof typeof MOL_ASPECT_HINTS;

export function Molecule({
  chemicalId,
  smiles,
  label,
  size = "lg",
  alt,
  noStructureText,
}: {
  chemicalId: number;
  smiles?: string | null;
  label?: string | null;
  /** 宽高比提示档位 */
  size?: MolSizeKey;
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
  const hint = MOL_ASPECT_HINTS[size];
  return (
    <img
      src={molSvgUrl(chemicalId)}
      width={hint.width}
      height={hint.height}
      alt=""
      role="img"
      aria-label={alt ?? t.chemical.structureAlt(name)}
      loading="lazy"
      onError={() => setLoadError(true)}
    />
  );
}
