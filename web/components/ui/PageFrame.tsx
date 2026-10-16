import type { ReactNode } from "react";

/**
 * PageFrame — 全站唯一页面框架（版式基准）。
 *
 * 内容最大宽 1200（--w-wide），与顶栏 .sh-inner 同一条宽度公式，
 * 左缘与顶栏 logo 对齐；窄于 1240 时两侧各留 20。
 * reading = 阅读窄档（720），form = 表单窄档（400）。
 */
export function PageFrame({
  children,
  tier = "page",
  className,
}: {
  children: ReactNode;
  /** page 1200 / reading 720 / form 400（三档都是 token） */
  tier?: "page" | "reading" | "form";
  className?: string;
}) {
  const tierClass = tier === "page" ? "" : ` hg-page-frame--${tier}`;
  return (
    <div className={`hg-page-frame${tierClass}${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}
