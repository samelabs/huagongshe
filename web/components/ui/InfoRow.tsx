import type { ReactNode } from "react";

/**
 * InfoRow — 信息行（版式基准）：标签列 + 值列。
 * 化合物详情字段行的统一形态：标签列 140（手机 96），
 * 标签 muted 13，值 14，行间 1px 分割线。
 */
export function InfoRow({
  label,
  children,
  mono = false,
}: {
  label: ReactNode;
  children: ReactNode;
  /** 标识符等值用等宽字体 */
  mono?: boolean;
}) {
  return (
    <dl className="hg-info-row">
      <dt>{label}</dt>
      <dd className={mono ? "mono" : undefined}>{children}</dd>
    </dl>
  );
}
