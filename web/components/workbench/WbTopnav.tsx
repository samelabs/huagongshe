"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";

export function WbTopnav() {
  const t = useDictionary();
  const locale = useLocale();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  // active 判定只看剥离 locale 前缀后的 pathname, locale 不参与业务规则
  const routePath = stripLocalePrefix(pathname ?? "/");
  const items = [
  { href: "/aichem", label: t.me.navHome, kind: "nav",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>),
    match: (p: string, search: string) => p === "/aichem" && !search.includes("tab="),
  },
  { href: "/aichem?tab=search", label: t.me.navSearch, kind: "nav",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></svg>),
    match: (_p: string, search: string) => search.includes("tab=search"),
  },
  { href: "/aichem?tab=notes&new=1", label: t.me.navNewNote, kind: "action",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h14v16H5z" /><path d="M8 8h8M8 12h8" /></svg>),
    match: (_p: string, search: string) => search.includes("tab=notes") && search.includes("new=1"),
  },
  { href: "/submit", label: t.me.navNewReaction, kind: "action",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>),
    match: (p: string) => p.startsWith("/submit"),
  },
];

  return (
    <nav className="wb-topnav" aria-label={t.nav.mainNav}>
      {items.map((item) => {
        const active = item.match(routePath, search);
        return (
          <Link key={item.href} href={withLocale(item.href, locale)} aria-label={item.label}
            className={`wb-topnav-link wb-topnav-link-${item.kind}${active ? " active" : ""}`}>
            <span className="wb-topnav-icon">{item.icon}</span>
            <span className="wb-topnav-label">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
