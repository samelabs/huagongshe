"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

export function LoginRequired({ text }: { text: string }) {
  const t = useDictionary();
  const locale = useLocale();
  const pathname = usePathname();
  return <div className="auth-required"><div><strong>{t.common.loginRequired}</strong><span>{text}</span></div><Link href={withLocale(`/login?next=${encodeURIComponent(pathname)}`, locale)}>{t.auth.submit('login')}</Link></div>;
}
