"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/me/settings", label: "设置首页", exact: true },
  { href: "/me/settings/profile", label: "公开资料" },
  { href: "/me/settings/avatar", label: "头像" },
  { href: "/me/settings/security", label: "密码安全" },
  { href: "/me/settings/api-tokens", label: "API Token" },
];

export function SettingsNav() {
  const pathname = usePathname();
  return <nav className="settings-nav" aria-label="账户设置">
    {items.map((item) => {
      const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
      return <Link className={active ? "active" : ""} href={item.href} key={item.href}>{item.label}</Link>;
    })}
  </nav>;
}
