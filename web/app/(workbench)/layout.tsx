import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/dashboard/WorkbenchNav";
import { WbMobileNav } from "@/components/dashboard/WbMobileNav";
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
  const name = summary?.display_name || user.display_name;
  const username = summary?.username || user.username;
  const avatar = summary?.avatar_url || user.avatar_url;

  return (
    <div className="wb-shell">
      {/* 顶部 bar：纯个人信息（桌面右侧有操作按钮，手机有汉堡） */}
      <header className="wb-topbar">
        <div className="wb-topbar-user">
          <Link href={`/user/${encodeURIComponent(username)}`} className="wb-topbar-avatar">
            {avatar
              ? <img src={avatar} alt="" />
              : <span>{name.slice(0, 1)}</span>}
          </Link>
          <div className="wb-topbar-info">
            <strong>{name}</strong>
            <span>@{username}</span>
          </div>
        </div>

        {/* 桌面操作按钮 */}
        <div className="wb-topbar-actions">
          <Link className="wb-btn wb-btn-primary" href="/submit">{t.me.newReaction}</Link>
          <Link className="wb-btn wb-btn-ghost" href="/me/settings/api-tokens">{t.me.aiAssistant}</Link>
          <Link className="wb-btn wb-btn-ghost" href="/">{t.nav.home}</Link>
        </div>

        {/* 手机汉堡 */}
        <WbMobileNav>
          <Link className="wb-drawer-link wb-btn wb-btn-primary" href="/submit">{t.me.newReaction}</Link>
          <Link className="wb-drawer-link wb-btn wb-btn-ghost" href="/me/settings/api-tokens">{t.me.aiAssistant}</Link>
          <Link className="wb-drawer-link wb-btn wb-btn-ghost" href="/">{t.nav.home}</Link>
          <div className="wb-drawer-divider" />
          <Suspense><WorkbenchNav counts={counts} variant="drawer" /></Suspense>
        </WbMobileNav>
      </header>

      {/* 主体：桌面左右分栏，手机单列 */}
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
