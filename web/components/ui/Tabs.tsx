"use client";

/**
 * Tabs — 标签页（DESIGN_SYSTEM 3.7）：不同数据集之间切换，底部 2px 指示条，带计数。
 * role=tablist/tab、方向键（←→ Home End）切换、roving tabindex、可选计数。
 * 溢出时横向滚动并加 24 渐隐，不截断文字。受控组件：value + onChange。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type TabItem = { id: string; label: React.ReactNode; count?: number };

export function Tabs({ tabs, value, onChange, ariaLabel, className }: {
  tabs: ReadonlyArray<TabItem>;
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState<"none" | "left" | "right" | "both">("none");
  const activeIndex = Math.max(0, tabs.findIndex((t) => t.id === value));

  const updateFade = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const canScroll = el.scrollWidth > el.clientWidth + 1;
    if (!canScroll) {
      setFade("none");
      return;
    }
    const isAtStart = el.scrollLeft <= 1;
    const isAtEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1;
    if (isAtStart && !isAtEnd) setFade("right");
    else if (isAtEnd && !isAtStart) setFade("left");
    else if (!isAtStart && !isAtEnd) setFade("both");
    else setFade("none");
  }, []);

  useEffect(() => {
    updateFade();
    const el = listRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateFade, { passive: true });
    window.addEventListener("resize", updateFade);
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(updateFade);
      ro.observe(el);
    }
    return () => {
      el.removeEventListener("scroll", updateFade);
      window.removeEventListener("resize", updateFade);
      ro?.disconnect();
    };
  }, [updateFade, tabs]);

  function focusTab(index: number) {
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>("[role=tab]");
    buttons?.[index]?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const last = tabs.length - 1;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = activeIndex === last ? 0 : activeIndex + 1;
    else if (e.key === "ArrowLeft") next = activeIndex === 0 ? last : activeIndex - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next === null) return;
    e.preventDefault();
    const target = tabs[next];
    onChange(target.id);
    focusTab(next);
  }

  return (
    <div className="hg-tabs-wrap">
      <div
        className={["hg-tabs", className ?? ""].filter(Boolean).join(" ")}
        role="tablist"
        aria-label={ariaLabel}
        ref={listRef}
        onKeyDown={onKeyDown}
        data-fade={fade !== "none" ? fade : undefined}
      >
        {tabs.map((t) => {
          const selected = t.id === value;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`hg-tab-${t.id}`}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
            >
              {t.label}
              {t.count != null && <span className="ct">{t.count}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
