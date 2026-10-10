"use client";

/**
 * ShellUnread — 顶栏铃铛与手机底部 tab「动态」共用的未读数上下文。
 *
 * 数据来源 = 工作台计数同一接口 /users/me/dashboard（counts.unread），
 * 不新增 API。两种供给方式：
 * - 工作台 layout SSR 已取 dashboard → 经 SiteHeader 的 initialUnread 直传；
 * - 公开页 → 由本 Provider 在已登录时客户端请求（失败静默，未读数是
 *   装饰性信息）。
 *
 * 节流（v1.7 Step 6）：同一会话内最多 60 秒请求一次——时间戳存
 * sessionStorage（整页加载后依旧生效，真正按"会话"而非按模块实例计时）；
 * window 重新获得焦点时，距上次请求超过 60 秒才再取。
 */
import { createContext, useContext, useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { apiGet } from "@/lib/api";
import type { Summary } from "@/components/workbench/types";

const ShellUnreadContext = createContext<number>(0);

/** 会话级节流窗口 */
const THROTTLE_MS = 60_000;
const THROTTLE_KEY = "hgs.unreadLastFetch";

function lastRequestedAt(): number {
  try {
    return Number(sessionStorage.getItem(THROTTLE_KEY)) || 0;
  } catch {
    return 0; // sessionStorage 不可用（隐私模式等）→ 视为从未请求
  }
}

function markRequested(): void {
  try {
    sessionStorage.setItem(THROTTLE_KEY, String(Date.now()));
  } catch { /* 与读取同退化为不节流 */ }
}

export function useShellUnread(): number {
  return useContext(ShellUnreadContext);
}

export function ShellUnreadProvider({ initial = null, children }: {
  /** SSR 已取的 counts.unread；null = 由 Provider 自行请求 */
  initial?: number | null;
  children: React.ReactNode;
}) {
  const { user } = useAccount();
  const [unread, setUnread] = useState(initial ?? 0);
  const shouldFetch = user != null && initial == null;

  /* Step 9 Part B.4：进入动态面板标记已读后，WorkbenchCounts.refresh 触发
     router.refresh()，layout 重取 dashboard 并把新的 initialUnread 传下来。
     useState 初值只认首次挂载 —— 不跟随 prop 的话底部 tab 的未读徽标会一直
     停在旧值。SSR 值变化时同步进 state（null = 客户端自取模式不动）。 */
  useEffect(() => {
    if (initial != null) setUnread(initial);
  }, [initial]);

  useEffect(() => {
    if (!shouldFetch) return;
    let alive = true;
    const fetchIfStale = () => {
      if (Date.now() - lastRequestedAt() < THROTTLE_MS) return;
      markRequested();
      apiGet<Summary>("/users/me/dashboard")
        .then((s) => { if (alive) setUnread(s.counts?.unread ?? 0); })
        .catch(() => { /* 静默：红点不显示 */ });
    };
    fetchIfStale();
    window.addEventListener("focus", fetchIfStale);
    return () => {
      alive = false;
      window.removeEventListener("focus", fetchIfStale);
    };
  }, [shouldFetch]);

  return <ShellUnreadContext.Provider value={unread}>{children}</ShellUnreadContext.Provider>;
}
