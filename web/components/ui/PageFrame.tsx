import type { ReactNode } from "react";

/**
 * PageFrame — 全站唯一页面框架（版式基准）。
 *
 * 内容最大宽 1200（--w-wide），与顶栏 .sh-inner 同一条宽度公式，
 * 窄于 1240 时两侧各留 20。
 * content = 文档/列表宽档（1040，指南/MCP/数据API/Skills）；
 * reading = 阅读窄档（860，正文页限行长）；form = 表单窄档（400，单卡）。
 * 具体排布由页面场景决定（DESIGN_SYSTEM 2.2 / 2.4）。
 */
export function PageFrame({
  children,
  tier = "page",
  className,
}: {
  children: ReactNode;
  /** page 1200 / content 1040 / reading 860 / form 400（四档都是 token） */
  tier?: "page" | "content" | "reading" | "form";
  className?: string;
}) {
  const tierClass = tier === "page" ? "" : ` hg-page-frame--${tier}`;
  return (
    <div className={`hg-page-frame${tierClass}${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}
