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

export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

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

  useEffect(() => { void refresh(); }, [refresh]);
  const value = useMemo(() => ({ user, ready, refresh, clear: () => setUser(null) }), [user, ready, refresh]);
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useAccount must be used inside AccountProvider");
  return value;
}
