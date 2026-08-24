"use client";

import { useState, useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { WorkbenchNav } from "./WorkbenchNav";
import { AccountMenu } from "@/components/shared/AccountMenu";
import type { Counts } from "./types";
import type { User } from "@/lib/api";
import t from "@/lib/i18n";

/**
 * 移动端抽屉导航。
 * - 常驻 DOM，CSS transform 控制滑入/滑出（不走条件渲染）
 * - pathname 或 searchParams 变化时自动关闭（解决 tab 切换不收起）
 * - Escape / overlay 点击 / close 按钮均可关闭
 */
export function WbMobileNav({ counts, user }: {
  counts?: Counts | null;
  user: User;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const prevNav = useRef("");

  // pathname 或 query 变化 → 关闭（覆盖 tab 切换 /me/settings 等）
  const navKey = pathname + "?" + searchParams.toString();
  useEffect(() => {
    if (prevNav.current && prevNav.current !== navKey) setOpen(false);
    prevNav.current = navKey;
  }, [navKey]);

  // 锁定 body 滚动
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [open]);

  // Escape 关闭
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        className="wb-burger"
        aria-label={t.nav.menu}
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <line x1="4" y1="7" x2="20" y2="7" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="17" x2="20" y2="17" />
        </svg>
      </button>

      {/* overlay — 常驻 DOM，opacity + pointer-events 切换 */}
      <div
        className={`wb-drawer-overlay${open ? " open" : ""}`}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      {/* drawer — 常驻 DOM，transform translateX 切换 */}
      <aside
        className={`wb-drawer${open ? " open" : ""}`}
        role="dialog"
        aria-label={t.nav.menu}
        aria-hidden={!open}
      >
        <div className="wb-drawer-head">
          <AccountMenu user={user} variant="drawer" />
          <button className="wb-drawer-close" aria-label={t.common.close} onClick={() => setOpen(false)}>
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
  );
}
