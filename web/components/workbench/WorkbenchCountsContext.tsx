"use client";

import { createContext, useCallback, useContext, useRef } from "react";
import { useRouter } from "next/navigation";
import type { Counts } from "./types";

type WorkbenchCountsValue = {
  counts: Counts | null;
  refresh: () => void;
};

const WorkbenchCountsContext = createContext<WorkbenchCountsValue>({
  counts: null,
  refresh: () => {},
});

export function WorkbenchCountsProvider({
  counts,
  children,
}: {
  counts: Counts | null;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(() => {
    // 节流：500ms 内多次 refresh 只触发一次 router.refresh
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      router.refresh();
    }, 500);
  }, [router]);

  return (
    <WorkbenchCountsContext.Provider value={{ counts, refresh }}>
      {children}
    </WorkbenchCountsContext.Provider>
  );
}

export function useWorkbenchCounts() {
  return useContext(WorkbenchCountsContext);
}
