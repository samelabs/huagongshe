"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { label: "个人资料", href: "/me/settings/profile" },
  { label: "头像", href: "/me/settings/avatar" },
  { label: "账户安全", href: "/me/settings/security" },
  { label: "API Token", href: "/me/settings/api-tokens" },
];

export function SettingsNav() {
  const pathname = usePathname();
  return (
    <nav className="wb-nav" aria-label="设置导航">
      <div className="wb-nav-group">
        <p className="wb-nav-label">设置</p>
        {items.map((item) => {
          const active = pathname.startsWith(item.href);
          return <Link key={item.href} href={item.href} className={`wb-nav-link${active ? " active" : ""}`}><span>{item.label}</span></Link>;
        })}
      </div>
    </nav>
  );
}
