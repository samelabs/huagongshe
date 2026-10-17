import { cache } from "react";
import { headers } from "next/headers";
import { apiGet } from "@/lib/api.server";
import type { User } from "@/lib/api";
import type { Summary } from "@/components/workbench/types";
import { splitLocalePrefix } from "@/lib/localePath";

/**
 * shellData — 外壳（顶栏/底栏）与工作台 layout 共用的服务端数据。
 *
 * 顶栏在根 layout 只挂一次；工作台路由时它需要工作台的手机动作与
 * 未读数。这里用 React cache() 把请求按渲染合并 —— 根 layout 与
 * 工作台 layout 在同一次渲染里取同一份数据，不重复请求后端。
 */

/** 工作台路由族：/aichem 及其子页、/submit、/me（设置除外） */
function isWorkbenchRoute(rest: string): boolean {
  if (rest === "/aichem" || rest.startsWith("/aichem/")) return true;
  if (rest.startsWith("/submit")) return true;
  if (rest.startsWith("/me")) return true;
  return false;
}

export type ShellWorkbenchChrome = {
  user: User;
  counts: Summary["counts"] | null;
};

/** 笔记总数（侧栏「笔记」计数）：dashboard counts 不含笔记，
 *  用既有读接口 /users/me/notes?page_size=1 的 total 补齐（一次请求）。 */
async function getNotesCount(cookieHeader: string): Promise<number | null> {
  try {
    const page = await apiGet<{ total: number }>("/users/me/notes?page=1&page_size=1", { cookie: cookieHeader });
    return page.total;
  } catch { return null; }
}

/** 当前请求的工作台外壳数据；非工作台路由或匿名 → null（公开外壳）。 */
export const getShellWorkbenchChrome = cache(async (): Promise<ShellWorkbenchChrome | null> => {
  const h = await headers();
  // proxy 对带 locale 前缀的请求附带原始路径；无该头(未过 locale proxy 的
  // 直接访问)按公开外壳渲染。
  const localePath = h.get("x-site-locale-path");
  if (!localePath) return null;
  const stripped = splitLocalePrefix(localePath.split("?")[0]);
  const rest = stripped ? stripped.rest : localePath.split("?")[0];
  if (!isWorkbenchRoute(rest)) return null;

  const cookieHeader = h.get("cookie");
  if (!cookieHeader) return null;
  try {
    const user = await apiGet<User>("/users/me", { cookie: cookieHeader });
    if (!user) return null;
    let counts: Summary["counts"] | null = null;
    try {
      const summary = await apiGet<Summary>("/users/me/dashboard", { cookie: cookieHeader });
      const notesCount = await getNotesCount(cookieHeader);
      counts = summary?.counts
        ? { ...summary.counts, notes: notesCount ?? 0 }
        : null;
    } catch { /* 未取到计数时外壳只缺徽标，不阻塞渲染 */ }
    return { user, counts };
  } catch {
    return null;
  }
});
