import type { ReactNode } from "react";
import { CopyButton } from "./CopyButton";

/**
 * DataRow — DESIGN_SYSTEM 3.14/6.3/6.4 统一数据行（dl 内使用）。
 * dl 两列：标签列 140（手机 96），标签 var(--text-muted) 13px，
 * 值 var(--fs-14)，行间 1px 分割线（样式在 globals.css .chem-dl）。
 * over = 化合物页组级折叠的超限项（hidden + data-overflow，GroupToggle 翻转）。
 * mono = 等宽字体（用于标识符等）
 * copyable = 行内带 CopyButton（3.14 标识符行内复制）
 */
export function DataRow({
  label,
  value,
  children,
  over = false,
  mono = false,
  copyable = false,
  copyLabel,
}: {
  label: string;
  value?: string | null;
  children?: ReactNode;
  over?: boolean;
  mono?: boolean;
  copyable?: boolean;
  copyLabel?: string;
}) {
  if (value == null && children == null) return null;
  return (
    <div hidden={over || undefined} {...(over ? { "data-overflow": "" } : {})}>
      <dt>{label}</dt>
      <dd>
        {children ?? (
          copyable && value ? (
            <span className="hg-datarow-copy">
              <code className={mono ? "mono" : undefined}>{value}</code>
              <CopyButton value={value} ariaLabel={copyLabel ?? `Copy ${label}`} />
            </span>
          ) : mono && value ? (
            <code className="mono">{value}</code>
          ) : (
            value
          )
        )}
      </dd>
    </div>
  );
}

