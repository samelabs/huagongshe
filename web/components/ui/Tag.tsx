"use client";

/**
 * Tag — v1.7 标签（参考 §6）。neutral / blue / ok / warn / err / src；
 * dot=true 带状态圆点，icon 传任意图标组件。
 */
import type { ReactNode } from "react";

export type TagTone = "neutral" | "blue" | "ok" | "warn" | "err" | "src";

export function Tag({ tone = "neutral", dot, icon, children, className }: {
  tone?: TagTone;
  /** 状态圆点（取 currentColor） */
  dot?: boolean;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={["hg-tag", tone !== "neutral" ? tone : "", className ?? ""].filter(Boolean).join(" ")}>
      {dot && <i className="hg-dot" aria-hidden="true" />}
      {icon}
      {children}
    </span>
  );
}
