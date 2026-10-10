"use client";

/**
 * ShellUnread — 顶栏铃铛与手机底部 tab「动态」共用的未读数上下文。
 *
 * 数据来源 = 工作台计数同一接口 /users/me/dashboard（counts.unread），
 * 不新增 API。两种供给方式：
 * - 工作台 layout SSR 已取 dashboard → 经 SiteHeader 的 initialUnread 直传；
 * - 公开页 → 由本 Provider 在已登录时客户端请求一次（失败静默，未读数是
 *   装饰性信息）。
 */
import { createContext, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { apiGet } from "@/lib/api";
import type { Summary } from "@/components/workbench/types";

const ShellUnreadContext = createContext<number>(0);

export function useShellUnread(): number {
  return useContext(ShellUnreadContext);
}

export function ShellUnreadProvider({ initial = null, children }: {
  /** SSR 已取的 counts.unread；null = 由 Provider 自行请求 */
  initial?: number | null;
  children: React.ReactNode;
}) {
  const { user } = useAccount();
  const pathname = usePathname();
  const [unread, setUnread] = useState(initial ?? 0);
  const shouldFetch = user != null && initial == null;

  useEffect(() => {
    if (!shouldFetch) return;
    let alive = true;
    apiGet<Summary>("/users/me/dashboard")
      .then((s) => { if (alive) setUnread(s.counts?.unread ?? 0); })
      .catch(() => { /* 静默：红点不显示 */ });
    return () => { alive = false; };
  }, [shouldFetch, pathname]);

  return <ShellUnreadContext.Provider value={unread}>{children}</ShellUnreadContext.Provider>;
}
