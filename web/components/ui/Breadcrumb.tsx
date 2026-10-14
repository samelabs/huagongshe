"use client";

/**
 * Breadcrumb — 面包屑导航（DESIGN_SYSTEM 3.8）。
 * 首页 / 栏目 / 当前。首级“首页”可点；栏目为不可点击的文字；末级 = 页面 H1 的文本。字号 13。
 * 本轮只实现组件，不改页面。
 */
import type { ReactNode } from "react";
import Link from "next/link";

export type BreadcrumbItem = {
  label: ReactNode;
  href?: string;
};

export function Breadcrumb({
  items,
  className,
}: {
  items: BreadcrumbItem[];
  className?: string;
}) {
  if (!items || items.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className={`hg-breadcrumb${className ? ` ${className}` : ""}`}>
      <ol style={{ display: "contents", listStyle: "none", margin: 0, padding: 0 }}>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={index} style={{ display: "inline-flex", alignItems: "center", gap: "var(--sp-2)" }}>
              {index > 0 && <span className="sep" aria-hidden="true">/</span>}
              {isLast ? (
                <span aria-current="page">{item.label}</span>
              ) : item.href ? (
                <Link href={item.href}>{item.label}</Link>
              ) : (
                <span>{item.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
