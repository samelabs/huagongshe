import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/workbench/WorkbenchNav";
import { WorkbenchCountsProvider } from "@/components/workbench/WorkbenchCountsContext";
import { getShellWorkbenchChrome } from "@/lib/shellData";
import { ShellWorkbenchChromeSync } from "@/components/shell/ShellWorkbenchChrome";
import { getRequestLocale } from "@/lib/serverI18n";
import { withLocale, splitLocalePrefix } from "@/lib/localePath";
import "./aichem-tokens.css";
import "./aichem.css";

/** 工作台 layout：鉴权 + 侧栏 + 计数上下文。
 * 顶栏与手机底栏由根 layout 的外壳统一挂载；本 layout 挂 Sync 把这里
 * 取到的外壳数据写进顶栏的工作台上下文（站内切进工作台时顶栏随之出现
 * 手机动作，不重挂外壳），与外壳共用同一份缓存取数，不重复请求。 */
export default async function WorkbenchLayout({ children }: { children: React.ReactNode }) {
  const locale = await getRequestLocale();
  const chrome = await getShellWorkbenchChrome();
  if (!chrome) {
    // 匿名统一 locale-aware: /ja/aichem → /ja/login?next=/ja/aichem。
    // proxy rewrite 附带 x-site-locale-path 还原原始带前缀路径;
    // 无该 header(未过 locale proxy 的直接访问)保持既有 /login?next=/aichem。
    const h = await headers();
    const originalPath = h.get("x-site-locale-path");
    if (originalPath && splitLocalePrefix(originalPath.split("?")[0])) {
      redirect(withLocale(`/login?next=${encodeURIComponent(originalPath)}`, locale));
    }
    redirect("/login?next=/aichem");
  }
  const { user, counts } = chrome;

  return (
    <div className="wb-shell">
      <ShellWorkbenchChromeSync chrome={chrome} />
      <WorkbenchCountsProvider counts={counts}>
        <div className="wb-body">
          <aside className="wb-aside">
            {/* 2.3 / 6.7：桌面侧栏不再放「新建反应/新建笔记」，
                创建入口移概览页标题行；手机抽屉顶部仍保留一份（WbMobileNav）。 */}
            <Suspense><WorkbenchNav counts={counts} variant="sidebar" /></Suspense>
          </aside>
          <main className="wb-main">{children}</main>
        </div>
      </WorkbenchCountsProvider>
    </div>
  );
}
