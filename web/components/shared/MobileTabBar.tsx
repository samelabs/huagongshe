"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import t from "@/lib/i18n";

export function MobileTabBar() {
  const pathname = usePathname();

  const tabs = [
    { href: "/search", label: t.nav.tabSearch, icon: searchIcon, match: (p: string) => p === "/" || p.startsWith("/search") || p.startsWith("/chemical") || p.startsWith("/reaction") || p.startsWith("/skills") || p.startsWith("/guide") },
    { href: "/aichem", label: t.nav.tabWorkbench, icon: flaskIcon, match: (p: string) => p === "/aichem" || p.startsWith("/aichem?") || p.startsWith("/submit") },
    { href: "/me/settings/profile", label: t.nav.tabMe, icon: userIcon, match: (p: string) => p.startsWith("/me/settings") || p.startsWith("/user/") },
  ];

  return (
    <nav className="mobile-tab-bar" aria-label={t.nav.bottomNav}>
      {tabs.map((tab) => {
        const active = tab.match(pathname);
        return (
          <Link key={tab.href} href={tab.href} className={`tab-item ${active ? "active" : ""}`} aria-current={active ? "page" : undefined}>
            <span className="tab-icon">{tab.icon(active)}</span>
            <span className="tab-label">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function searchIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--blue)" : "var(--quiet)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </svg>
  );
}

function flaskIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--blue)" : "var(--quiet)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6" />
      <path d="M10 3v6.5L5 18a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-8.5V3" />
      <path d="M7.5 15h9" />
    </svg>
  );
}

function userIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--blue)" : "var(--quiet)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}
