"use client";

/**
 * ChemPageNav — 化合物详情页内导航（v1.7 Step 6，§9.1）。
 *
 * 两个形态共用一份 section 列表与高亮逻辑（IntersectionObserver）：
 * - variant="rail"：桌面右侧栏列表，sticky top var(--sp-6)，当前项
 *   var(--action) + 2px 左边线（参考 .rail nav）。
 * - variant="tabs"：≤900 顶部横向 Tabs，position:sticky; top:0，可横向滚动，
 *   点击跳锚点（目标 section 由 CSS scroll-margin-top 让位）。
 *
 * sections 由服务端传入——只包含页面上实际渲染的节。
 */
import { useEffect, useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";

type Section = [anchor: string, label: string];

export function ChemPageNav({ sections, variant }: { sections: Section[]; variant: "rail" | "tabs" }) {
  const t = useDictionary();
  const [active, setActive] = useState<string>(sections[0]?.[0] ?? "");

  useEffect(() => {
    if (sections.length === 0) return;
    setActive(sections[0][0]);
    // 高亮带：视口上部 20%–40% 区间内最靠上的 section 即「当前节」
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: [0, 0.2, 0.5] },
    );
    for (const [anchor] of sections) {
      const el = document.getElementById(anchor);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [sections]);

  if (sections.length === 0) return null;

  if (variant === "tabs") {
    return (
      <nav className="chem-tabs-nav" aria-label={t.chemical.page.onThisPage}>
        {sections.map(([anchor, label]) => (
          <a key={anchor} href={`#${anchor}`} aria-current={active === anchor ? "true" : undefined} className={active === anchor ? "on" : undefined}>
            {label}
          </a>
        ))}
      </nav>
    );
  }

  return (
    <nav className="chem-rail-nav" aria-label={t.chemical.page.onThisPage}>
      <b className="chem-rail-nav-title">{t.chemical.page.onThisPage}</b>
      {sections.map(([anchor, label]) => (
        <a key={anchor} href={`#${anchor}`} aria-current={active === anchor ? "true" : undefined} className={active === anchor ? "on" : undefined}>
          {label}
        </a>
      ))}
    </nav>
  );
}
