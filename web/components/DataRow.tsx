import type { ReactNode } from "react";

/**
 * DataRow — §9.1/§9.2 统一数据行（dl 内使用）。
 * dl 两列：标签列 140（手机 96），标签 var(--text-muted) 13px，
 * 值 var(--fs-14)，行间 1px 分割线（样式在 globals.css .chem-dl）。
 * over = 化合物页组级折叠的超限项（hidden + data-overflow，GroupToggle 翻转）。
 */
export function DataRow({ label, value, children, over = false }: {
  label: string;
  value?: string | null;
  children?: ReactNode;
  over?: boolean;
}) {
  if (value == null && children == null) return null;
  return <div hidden={over || undefined} {...(over ? { "data-overflow": "" } : {})}><dt>{label}</dt><dd>{children ?? value}</dd></div>;
}
