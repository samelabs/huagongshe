import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/workbench/WorkbenchNav";
import { WbMobileNav } from "@/components/workbench/WbMobileNav";
import { WbTopnav } from "@/components/workbench/WbTopnav";
import { AccountMenu } from "@/components/shared/AccountMenu";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";
import { WorkbenchCountsProvider } from "@/components/workbench/WorkbenchCountsContext";
import { MobileTabBar } from "@/components/shared/MobileTabBar";
import { headers as nextHeaders } from "next/headers";
import { apiGet } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale, splitLocalePrefix } from "@/lib/localePath";
import { HgsLogo } from "@/components/ui/HgsLogo";
import type { User } from "@/lib/api";
import type { Summary } from "@/components/workbench/types";
import "./aichem-tokens.css";
import "./aichem.css";

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

async function getSummary(cookieHeader: string): Promise<Summary | null> {
  try {
    return await apiGet<Summary>("/users/me/dashboard", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function WorkbenchLayout({ children }: { children: React.ReactNode }) {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) {
    // 匿名统一 locale-aware: /ja/aichem → /ja/login?next=/ja/aichem。
    // proxy rewrite 附带 x-site-locale-path 还原原始带前缀路径;
    // 无该 header(未过 locale proxy 的直接访问)保持既有 /login?next=/aichem。
    // locale 前缀判定复用唯一 parser splitLocalePrefix, 不再硬编码五语言 regex。
    const originalPath = (await nextHeaders()).get("x-site-locale-path");
    if (originalPath && splitLocalePrefix(originalPath.split("?")[0])) {
      redirect(withLocale(`/login?next=${encodeURIComponent(originalPath)}`, locale));
    }
    redirect("/login?next=/aichem");
  }
  const summary = cookieHeader ? await getSummary(cookieHeader) : null;
  const counts = summary?.counts ?? null;

  return (
    <div className="wb-shell">
      <header className="wb-topbar">
        <div className="wb-topbar-inner">
          <Link href={withLocale("/", locale)} className="wb-logo" aria-label={t.nav.home}>
            <HgsLogo variant="lockup" locale={locale} />
          </Link>

          <WbTopnav />

          <div className="wb-topbar-user">
            <div className="wb-topbar-language">
              <LanguageSwitcher />
            </div>
            <AccountMenu user={user} variant="topbar" />
          </div>

          <WbMobileNav counts={counts} user={user} />
        </div>
      </header>

      <WorkbenchCountsProvider counts={counts}>
        <div className="wb-body">
          <aside className="wb-aside">
            <Suspense><WorkbenchNav counts={counts} variant="sidebar" /></Suspense>
          </aside>
          <main className="wb-main">{children}</main>
        </div>
      </WorkbenchCountsProvider>

      <MobileTabBar />
    </div>
  );
}
