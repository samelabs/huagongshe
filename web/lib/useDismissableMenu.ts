"use client";

/**
 * useDismissableMenu — 站内浮层统一回收规则。
 *
 * 一份实现，四处使用（语言切换、顶栏头像/更多菜单、底栏用户菜单、
 * 化合物更多菜单）。回收触发：
 *  - 外部点击（pointerdown 落在容器之外）
 *  - 焦点移出（focusout 离开容器，含移到浏览器地址栏）
 *  - Esc（关闭并把焦点还给触发器）
 *  - 路由变化（pathname 变更即收起）
 * 另含方向键在菜单项（[data-menu-item]）间的移动。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

export function useDismissableMenu() {
  const [open, setOpen] = useState(false);
  /** 触发器 + 面板的共同容器 */
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const pathname = usePathname();
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => { setOpen(false); }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const root = rootRef.current;
    function onPointerDown(e: PointerEvent) {
      if (root && !root.contains(e.target as Node)) close();
    }
    function onFocusOut(e: FocusEvent) {
      const next = e.relatedTarget;
      if (!next || !root?.contains(next as Node)) close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      // 只收最内层浮层：本层处理了 Esc 就不再传给外层（如抽屉）
      e.stopImmediatePropagation();
      close();
      triggerRef.current?.focus();
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    root?.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      root?.removeEventListener("focusout", onFocusOut);
    };
  }, [open, close]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      triggerRef.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const panel = rootRef.current;
    if (!panel) return;
    const items = Array.from(panel.querySelectorAll<HTMLElement>("[data-menu-item]"))
      .filter((el) => el.offsetParent !== null);
    if (items.length === 0) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "ArrowDown"
      ? items[(index + 1 + items.length) % items.length]
      : items[(index - 1 + items.length) % items.length];
    next.focus();
  }, [open, close]);

  return { open, setOpen, rootRef, triggerRef, onKeyDown, close };
}
