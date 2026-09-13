import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/workbench/WorkbenchNav";
import { WbMobileNav } from "@/components/workbench/WbMobileNav";
import { WbTopnav } from "@/components/workbench/WbTopnav";
import { AccountMenu } from "@/components/shared/AccountMenu";
import { WorkbenchCountsProvider } from "@/components/workbench/WorkbenchCountsContext";
import { MobileTabBar } from "@/components/shared/MobileTabBar";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import type { Summary } from "@/components/workbench/types";
import t from "@/lib/i18n";
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
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) redirect("/login?next=/aichem");
  const summary = cookieHeader ? await getSummary(cookieHeader) : null;
  const counts = summary?.counts ?? null;

  return (
    <div className="wb-shell">
      <header className="wb-topbar">
        <div className="wb-topbar-inner">
          <Link href="/" className="wb-logo">{t.brand.name}</Link>

          <WbTopnav />

          <div className="wb-topbar-user">
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
