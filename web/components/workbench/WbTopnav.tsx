"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

export function WbTopnav() {
  const t = useDictionary();
  const locale = useLocale();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const items = [
  { href: "/aichem", label: t.me.navHome,
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>),
    match: (p: string, search: string) => p === "/aichem" && !search.includes("tab="),
  },
  { href: "/aichem?tab=search", label: t.me.navSearch,
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></svg>),
    match: (_p: string, search: string) => search.includes("tab=search"),
  },
  { href: "/submit", label: t.me.navNewReaction,
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>),
    match: (p: string) => p.startsWith("/submit"),
  },
];

  return (
    <nav className="wb-topnav" aria-label={t.nav.mainNav}>
      {items.map((item) => {
        const active = item.match(pathname, search);
        return (
          <Link key={item.href} href={withLocale(item.href, locale)} className={`wb-topnav-link${active ? " active" : ""}`}>
            <span className="wb-topnav-icon">{item.icon}</span>
            <span className="wb-topnav-label">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
