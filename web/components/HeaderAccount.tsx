"use client";

import Link from "next/link";
import { useAccount } from "@/components/shared/AccountContext";
import { AccountMenu } from "@/components/shared/AccountMenu";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

export function HeaderAccount() {
  const { user } = useAccount();
  const t = useDictionary();
  const locale = useLocale();

  return (
    <nav aria-label={t.nav.mainNav}>
      <Link href={withLocale("/mcp-guide", locale)} className="nav-guide" aria-label="MCP">
        MCP
      </Link>
      <LanguageSwitcher />
      {user ? (
        <AccountMenu user={user} variant="header" showWorkbenchEntry />
      ) : (
        <Link href={withLocale("/login", locale)} className="login-link">{t.nav.login}</Link>
      )}
    </nav>
  );
}
