"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { WorkbenchNav } from "./WorkbenchNav";
import type { Counts } from "./types";

export function WbMobileNav({ counts }: { counts?: Counts | null }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [open]);

  return (
    <>
      <button
        className="wb-burger"
        aria-label="打开导航菜单"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <line x1="4" y1="7" x2="20" y2="7" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="17" x2="20" y2="17" />
        </svg>
      </button>

      {open && (
        <>
          <div className="wb-drawer-overlay" onClick={() => setOpen(false)} />
          <aside className="wb-drawer" role="dialog" aria-label="工作台导航菜单">
            <div className="wb-drawer-head">
              <span>导航</span>
              <button className="wb-drawer-close" aria-label="关闭" onClick={() => setOpen(false)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="18" y1="6" x2="6" y2="18" />
                </svg>
              </button>
            </div>
            <div className="wb-drawer-body">
              <WorkbenchNav counts={counts} variant="drawer" />
            </div>
          </aside>
        </>
      )}
    </>
  );
}
