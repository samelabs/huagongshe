import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/dashboard/WorkbenchNav";
import { WbMobileNav } from "@/components/dashboard/WbMobileNav";
import { WbTopnav } from "@/components/dashboard/WbTopnav";
import { MobileTabBar } from "@/components/MobileTabBar";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import type { Summary } from "@/components/dashboard/types";
import t from "@/lib/i18n";

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
          <Link href="/" className="wb-logo">AIchem</Link>

          <WbTopnav />

          <div className="wb-topbar-user">
            <Link href={`/user/${encodeURIComponent(user.username)}`} className="wb-topbar-avatar">
              {(summary?.avatar_url || user.avatar_url)
                ? <img src={summary?.avatar_url || user.avatar_url || ""} alt="" />
                : <span>{(summary?.display_name || user.display_name).slice(0, 1)}</span>}
            </Link>
            <div className="wb-topbar-info">
              <strong>{summary?.display_name || user.display_name}</strong>
              <span>@{summary?.username || user.username}</span>
            </div>
          </div>

          <WbMobileNav counts={counts} />
        </div>
      </header>

      <div className="wb-content">
        <div className="wb-content-inner">
          <Suspense><WorkbenchNav counts={counts} variant="sidebar" /></Suspense>
          <main className="wb-main">{children}</main>
        </div>
      </div>

      <MobileTabBar />
    </div>
  );
}
