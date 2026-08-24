"use client";

import Link from "next/link";
import { useAccount } from "@/components/shared/AccountContext";
import { AccountMenu } from "@/components/shared/AccountMenu";
import t from "@/lib/i18n";

export function HeaderAccount() {
  const { user } = useAccount();

  return (
    <nav aria-label={t.nav.mainNav}>
      <Link href="/guide" className="nav-guide" aria-label={t.nav.guide}>
        <span className="guide-full">{t.nav.guide}</span><span className="guide-short">AI</span>
      </Link>
      {user ? (
        <AccountMenu user={user} variant="header" showWorkbenchEntry />
      ) : (
        <Link href="/login" className="login-link">{t.nav.login}</Link>
      )}
    </nav>
  );
}
