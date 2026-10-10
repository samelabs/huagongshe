import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/workbench/WorkbenchNav";
import { WbMobileNav } from "@/components/workbench/WbMobileNav";
import { WbQuickActions } from "@/components/workbench/WbQuickActions";
import { WorkbenchCountsProvider } from "@/components/workbench/WorkbenchCountsContext";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { apiGet } from "@/lib/api";
import { getRequestLocale } from "@/lib/serverI18n";
import { withLocale, splitLocalePrefix } from "@/lib/localePath";
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
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) {
    // 匿名统一 locale-aware: /ja/aichem → /ja/login?next=/ja/aichem。
    // proxy rewrite 附带 x-site-locale-path 还原原始带前缀路径;
    // 无该 header(未过 locale proxy 的直接访问)保持既有 /login?next=/aichem。
    // locale 前缀判定复用唯一 parser splitLocalePrefix, 不再硬编码五语言 regex。
    const originalPath = h.get("x-site-locale-path");
    if (originalPath && splitLocalePrefix(originalPath.split("?")[0])) {
      redirect(withLocale(`/login?next=${encodeURIComponent(originalPath)}`, locale));
    }
    redirect("/login?next=/aichem");
  }
  const summary = cookieHeader ? await getSummary(cookieHeader) : null;
  const counts = summary?.counts ?? null;

  return (
    <div className="wb-shell">
      {/* v1.7 顶栏统一：全站共用 SiteHeader（原 wb-topbar/WbTopnav 删除）。
          未读数直传服务端已取的 counts.unread；手机端汉堡按钮（抽屉）经插槽进顶栏；
          手机底部 tab 由 SiteHeader 内部挂载（与顶栏共用未读上下文）。 */}
      <SiteHeader
        initialUnread={counts?.unread ?? 0}
        mobileActions={<WbMobileNav counts={counts} user={user} />}
      />

      <WorkbenchCountsProvider counts={counts}>
        <div className="wb-body">
          <aside className="wb-aside">
            {/* 临时安置（Step 8 重做工作台时调整位置）：原顶栏「新建反应 / 新建笔记」入口 */}
            <WbQuickActions />
            <Suspense><WorkbenchNav counts={counts} variant="sidebar" /></Suspense>
          </aside>
          <main className="wb-main">{children}</main>
        </div>
      </WorkbenchCountsProvider>
    </div>
  );
}
