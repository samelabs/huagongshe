"use client";

/**
 * WbCreateMenu — 手机（≤640）工作台顶栏右侧「+」创建菜单（§12 第二屏）。
 *
 * 概览标题行的「新建笔记/新建反应」在手机上收进这里（两项菜单）；
 * 仅在 /aichem 概览 tab 显示（其余工作台页不出现）。Esc 关闭、焦点回
 * 「+」、外点关闭；桌面隐藏（CSS .wb-create）。
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { IconPlus } from "@/components/ui/icons";

export function WbCreateMenu() {
  const t = useDictionary();
  const locale = useLocale();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") || "home";
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // 只在概览出现
  if (tab !== "home") return null;

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (!panelRef.current?.contains(e.target as Node) && !triggerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={`wb-create${open ? " open" : ""}`}>
      <button
        ref={triggerRef}
        type="button"
        className="hg-btn ghost icon wb-create-trigger"
        aria-label={t.me.createMenuLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <IconPlus />
      </button>
      {open && (
        <div ref={panelRef} className="wb-create-panel" role="menu">
          <Link role="menuitem" href={withLocale("/submit", locale)} onClick={() => setOpen(false)}>{t.me.navNewReaction}</Link>
          <Link role="menuitem" href={withLocale("/aichem?tab=notes&new=1", locale)} onClick={() => setOpen(false)}>{t.me.navNewNote}</Link>
        </div>
      )}
    </div>
  );
}
