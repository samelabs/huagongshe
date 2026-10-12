"use client";

/**
 * Skeleton — 加载骨架（参考 §6，IX-4「列表加载用骨架屏」）。
 * card：卡片块占位；row：列表行占位。
 */
export function Skeleton({ variant = "row", className, style }: {
  variant?: "card" | "row";
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={["hg-sk", variant, className ?? ""].filter(Boolean).join(" ")} style={style} aria-hidden="true" />;
}
