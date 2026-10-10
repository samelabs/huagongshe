"use client";

import { useState, useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { WorkbenchNav } from "./WorkbenchNav";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import type { Counts } from "./types";
import type { User } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";

/**
 * 移动端抽屉导航（v1.7 Step 5 起挂到 SiteHeader 的 mobileActions 插槽）。
 * - 常驻 DOM，CSS transform 控制滑入/滑出（不走条件渲染）
 * - pathname 或 searchParams 变化时自动关闭（解决 tab 切换不收起）
 * - Escape / overlay 点击 / close 按钮均可关闭
 * - 内容 = 侧栏入口的镜像：快捷操作（新建反应/新建笔记）+ 语言 + 工作台导航；
 *   身份菜单在顶栏头像（UserMenu），底部四 tab 由 MobileTabBar 承担，互不重复
 */
export function WbMobileNav({ counts, user }: {
  counts?: Counts | null;
  user: User;
}) {
  const t = useDictionary();
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
      <Button
        variant="ghost"
        iconOnly
        aria-label={t.nav.menu}
        aria-expanded={open}
        className="wb-burger"
        onClick={() => setOpen(true)}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <line x1="4" y1="7" x2="20" y2="7" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="17" x2="20" y2="17" />
        </svg>
      </Button>

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
        inert={!open}
      >
        <div className="wb-drawer-head">
          <div className="wb-drawer-user">
            <Avatar id={user.id} name={user.display_name} src={user.avatar_url} size={32} />
            <div className="wb-drawer-user-meta">
              <strong>{user.display_name}</strong>
              <span>@{user.username}</span>
            </div>
          </div>
          <Button variant="ghost" iconOnly aria-label={t.common.close} className="wb-drawer-close" onClick={() => setOpen(false)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <line x1="6" y1="6" x2="18" y2="18" />
              <line x1="18" y1="6" x2="6" y2="18" />
            </svg>
          </Button>
        </div>

        <div className="wb-drawer-body">
          <div className="wb-drawer-language">
            <LanguageSwitcher />
          </div>

          <WorkbenchNav counts={counts} variant="drawer" />
        </div>
      </aside>
    </>
  );
}
