"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "首页",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>),
    match: (p: string) => p === "/",
  },
  { href: "/submit", label: "新建反应",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>),
    match: (p: string) => p.startsWith("/submit"),
  },
  { href: "/guide", label: "AI指南",
    icon: (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>),
    match: (p: string) => p.startsWith("/guide"),
  },
];

export function WbTopnav() {
  const pathname = usePathname();
  return (
    <nav className="wb-topnav" aria-label="主导航">
      {items.map((item) => {
        const active = item.match(pathname);
        return (
          <Link key={item.href} href={item.href} className={`wb-topnav-link${active ? " active" : ""}`}>
            <span className="wb-topnav-icon">{item.icon}</span>
            <span className="wb-topnav-label">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
