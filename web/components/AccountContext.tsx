"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { User } from "@/lib/api";

type AccountContextValue = {
  user: User | null;
  ready: boolean;
  refresh: () => Promise<void>;
  clear: () => void;
};

const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({ children, initialUser }: { children: React.ReactNode; initialUser: User | null }) {
  const [user, setUser] = useState<User | null>(initialUser);
  // SSR already resolved the user authoritatively. ready is true from first paint
  // so the header never flashes a placeholder before settling on its final state.
  const [ready, setReady] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/users/me", { cache: "no-store" });
      setUser(response.ok ? await response.json() as User : null);
    } catch {
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  // Only re-check when SSR had no user (e.g. stale SW cache served the HTML).
  // The SSR result is already authoritative for normal browsing.
  useEffect(() => { if (!initialUser) void refresh(); }, [refresh, initialUser]);
  const value = useMemo(() => ({ user, ready, refresh, clear: () => setUser(null) }), [user, ready, refresh]);
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useAccount must be used inside AccountProvider");
  return value;
}
