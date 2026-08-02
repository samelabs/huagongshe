"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import t from "@/lib/i18n";

export function LoginRequired({ text }: { text: string }) {
  const pathname = usePathname();
  return <div className="auth-required"><div><strong>{t.common.loginRequired}</strong><span>{text}</span></div><Link href={`/login?next=${encodeURIComponent(pathname)}`}>{t.auth.submit('login')}</Link></div>;
}
