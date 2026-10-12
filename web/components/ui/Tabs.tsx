"use client";

/**
 * Tabs — 标签页（参考 §6）：role=tablist/tab、方向键（←→ Home End）切换、
 * roving tabindex、可选计数。受控组件：value + onChange。
 */
import { useRef } from "react";

export type TabItem = { id: string; label: React.ReactNode; count?: number };

export function Tabs({ tabs, value, onChange, ariaLabel, className }: {
  tabs: ReadonlyArray<TabItem>;
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const activeIndex = Math.max(0, tabs.findIndex((t) => t.id === value));

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
    <div className={["hg-tabs", className ?? ""].filter(Boolean).join(" ")} role="tablist" aria-label={ariaLabel} ref={listRef} onKeyDown={onKeyDown}>
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
  );
}
