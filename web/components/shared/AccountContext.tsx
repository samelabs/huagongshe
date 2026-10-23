"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { User } from "@/lib/api";
import { apiGet } from "@/lib/api";

type AccountContextValue = {
  user: User | null;
  ready: boolean;
  refresh: () => Promise<void>;
  clear: () => void;
};

const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({ children, initialUser, resolved }: { children: React.ReactNode; initialUser: User | null; resolved: boolean }) {
  const [user, setUser] = useState<User | null>(initialUser);
  // 服务端已确定登录态时首屏即就绪；共享缓存的页面由客户端取登录态。
  const [ready, setReady] = useState(resolved);

  const refresh = useCallback(async () => {
    try {
      const value = await apiGet<User>("/users/me");
      setUser(value);
    } catch {
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    // 只有共享缓存页(服务端未随请求解析登录态)由客户端补一次 /users/me;
    // 服务端已确认匿名(resolved 且无用户)不再复核, 免掉必然 401 的请求
    // (本站大头流量是爬虫)。会话 cookie 为 HttpOnly, 客户端无法预判有无
    // 凭证, 缓存页匿名访客在此路径收一次轻量 401(服务端无库查询)。
    if (!resolved) void refresh();
  }, [refresh, resolved]);
  const value = useMemo(() => ({ user, ready, refresh, clear: () => setUser(null) }), [user, ready, refresh]);
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useAccount must be used inside AccountProvider");
  return value;
}
