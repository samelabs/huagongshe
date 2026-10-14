"use client";

/**
 * Segmented — 分段控件（DESIGN_SYSTEM 3.7）：同一份数据的视图或模式切换。
 * role=group + aria-pressed。溢出时横向滚动并加 24 渐隐，不截断文字。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type SegmentedOption<T extends string> = { value: T; label: React.ReactNode };

export function Segmented<T extends string>({ options, value, onChange, ariaLabel, className }: {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState<"none" | "left" | "right" | "both">("none");

  const updateFade = useCallback(() => {
    const el = scrollRef.current;
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
    const el = scrollRef.current;
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
  }, [updateFade, options]);

  return (
    <div className="hg-seg-wrap">
      <div
        ref={scrollRef}
        className={["hg-seg", className ?? ""].filter(Boolean).join(" ")}
        role="group"
        aria-label={ariaLabel}
        data-fade={fade !== "none" ? fade : undefined}
      >
        {options.map((o) => (
          <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
