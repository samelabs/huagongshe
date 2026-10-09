"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";

export function MobileTabBar() {
  const t = useDictionary();
  const locale = useLocale();
  // active 判定只看剥离 locale 前缀后的 pathname, locale 不参与业务规则
  const routePath = stripLocalePrefix(usePathname() ?? "/");

  /* 底栏只承担三个顶级目的地; 站内检索/浏览(search/chemical/reaction/guide/skills)
     不是底栏 tab, 不参与 active 判定 —— 工作台内部搜索在 WbTopnav(/aichem?tab=search)。 */
  const tabs = [
    { href: "/", label: t.nav.tabHome, icon: homeIcon, match: (p: string) => p === "/" },
    { href: "/aichem", label: t.nav.tabWorkbench, icon: flaskIcon, match: (p: string) => p === "/aichem" || p.startsWith("/aichem?") || p.startsWith("/submit") },
    { href: "/me/settings/profile", label: t.nav.tabMe, icon: userIcon, match: (p: string) => p.startsWith("/me/settings") || p.startsWith("/user/") },
  ];

  return (
    <nav className="mobile-tab-bar" aria-label={t.nav.bottomNav}>
      {tabs.map((tab) => {
        const active = tab.match(routePath);
        return (
          <Link key={tab.href} href={withLocale(tab.href, locale)} className={`tab-item ${active ? "active" : ""}`} aria-current={active ? "page" : undefined}>
            <span className="tab-icon">{tab.icon(active)}</span>
            <span className="tab-label">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function homeIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--action)" : "var(--text-muted)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11l9-8 9 8" />
      <path d="M5 10v10h14V10" />
    </svg>
  );
}

function flaskIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--action)" : "var(--text-muted)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6" />
      <path d="M10 3v6.5L5 18a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-8.5V3" />
      <path d="M7.5 15h9" />
    </svg>
  );
}

function userIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--action)" : "var(--text-muted)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}
