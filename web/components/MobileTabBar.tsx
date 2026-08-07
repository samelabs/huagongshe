"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function MobileTabBar() {
  const pathname = usePathname();

  const tabs = [
    { href: "/search", label: "检索", icon: searchIcon, match: (p: string) => p === "/" || p.startsWith("/search") || p.startsWith("/chemical") || p.startsWith("/reaction") },
    { href: "/me", label: "知识库", icon: libraryIcon, match: (p: string) => p.startsWith("/me") },
    { href: "/me/settings/profile", label: "我的", icon: userIcon, match: (p: string) => p.startsWith("/me/settings") || p.startsWith("/user/") },
  ];

  return (
    <nav className="mobile-tab-bar" aria-label="底部导航">
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
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "#1e90ff" : "#829ab1"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </svg>
  );
}

function libraryIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "#1e90ff" : "#829ab1"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  );
}

function userIcon(active: boolean) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "#1e90ff" : "#829ab1"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}
