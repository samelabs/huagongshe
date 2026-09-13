"use client";

import Link from "next/link";
import { useAccount } from "@/components/shared/AccountContext";
import { AccountMenu } from "@/components/shared/AccountMenu";
import t from "@/lib/i18n";

export function HeaderAccount() {
  const { user } = useAccount();

  return (
    <nav aria-label={t.nav.mainNav}>
      <Link href="/mcp-guide" className="nav-guide" aria-label="MCP">
        MCP
      </Link>
      {user ? (
        <AccountMenu user={user} variant="header" showWorkbenchEntry />
      ) : (
        <Link href="/login" className="login-link">{t.nav.login}</Link>
      )}
    </nav>
  );
}
