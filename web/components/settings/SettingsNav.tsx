"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import t from "@/lib/i18n";

const items = [
  { href: "/me/settings/api-tokens", label: t.settings.nav.ai },
  { href: "/me/settings/profile", label: t.settings.nav.profile },
  { href: "/me/settings/avatar", label: t.settings.nav.avatar },
  { href: "/me/settings/security", label: t.settings.nav.security },
];

export function SettingsNav() {
  const pathname = usePathname();
  return <nav className="settings-nav" aria-label={t.settings.title}>
    {items.map((item) => {
      const active = pathname.startsWith(item.href);
      return <Link className={active ? "active" : ""} href={item.href} key={item.href}>{item.label}</Link>;
    })}
  </nav>;
}
