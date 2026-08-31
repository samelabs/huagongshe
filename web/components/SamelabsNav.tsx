"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import t from "@/lib/i18n";

const items = [
  { href: "/samelabs", label: t.admin.navDashboard },
  { href: "/samelabs/users", label: t.admin.navUsers },
  { href: "/samelabs/reactions", label: t.admin.navReactions },
  { href: "/samelabs/skills", label: t.admin.navSkills },
  { href: "/samelabs/config", label: t.admin.navConfig },
  { href: "/samelabs/workers", label: t.admin.navWorkers },
  { href: "/samelabs/pipeline", label: t.admin.navPipeline },
];

export function SamelabsNav() {
  const pathname = usePathname();
  return <nav className="admin-nav" aria-label={t.admin.title}>
    {items.map((item) => {
      const active = item.href === "/samelabs" ? pathname === "/samelabs" : pathname.startsWith(item.href);
      return <Link className={active ? "active" : ""} href={item.href} key={item.href}>{item.label}</Link>;
    })}
  </nav>;
}
