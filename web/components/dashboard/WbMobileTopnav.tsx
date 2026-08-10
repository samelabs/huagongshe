"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function WbMobileTopnav() {
  const pathname = usePathname();
  const items = [
    { href: "/", label: "首页", match: (p: string) => p === "/" },
    { href: "/guide", label: "AI指南", match: (p: string) => p.startsWith("/guide") },
    { href: "/submit", label: "新建反应", match: (p: string) => p.startsWith("/submit") },
  ];
  return (
    <nav className="wb-mobnav" aria-label="主导航">
      {items.map((item) => {
        const active = item.match(pathname);
        return (
          <Link key={item.href} href={item.href} className={`wb-mobnav-btn${active ? " active" : ""}`} aria-label={item.label}>
            {iconFor(item.href)}
          </Link>
        );
      })}
    </nav>
  );
}

function iconFor(href: string) {
  if (href === "/") {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 11l9-8 9 8" />
        <path d="M5 10v10h14V10" />
      </svg>
    );
  }
  if (href === "/guide") {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v4M12 16h.01" />
      </svg>
    );
  }
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}
