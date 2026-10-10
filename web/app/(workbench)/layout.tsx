import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/workbench/WorkbenchNav";
import { WbMobileNav } from "@/components/workbench/WbMobileNav";
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

/** 笔记总数（§9.4 侧栏「笔记」计数）：dashboard counts 不含笔记，
 *  用既有读接口 /users/me/notes?page_size=1 的 total 补齐（一次请求）。 */
async function getNotesCount(cookieHeader: string): Promise<number | null> {
  try {
    const page = await apiGet<{ total: number }>("/users/me/notes?page=1&page_size=1", { cookie: cookieHeader });
    return page.total;
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
  const notesCount = cookieHeader ? await getNotesCount(cookieHeader) : null;
  const counts = summary?.counts
    ? { ...summary.counts, notes: notesCount ?? 0 }
    : null;

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
            {/* Step 8 §9.4：桌面侧栏不再放「新建反应/新建笔记」，
                创建入口移概览页标题行；手机抽屉顶部仍保留一份（WbMobileNav）。 */}
            <Suspense><WorkbenchNav counts={counts} variant="sidebar" /></Suspense>
          </aside>
          <main className="wb-main">{children}</main>
        </div>
      </WorkbenchCountsProvider>
    </div>
  );
}
