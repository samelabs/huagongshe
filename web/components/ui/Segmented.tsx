"use client";

/**
 * Segmented — 分段控件（参考 §6）：role=group + aria-pressed，
 * 用于检索方式 / 视图切换，取代 chip 组。
 */
export type SegmentedOption<T extends string> = { value: T; label: React.ReactNode };

export function Segmented<T extends string>({ options, value, onChange, ariaLabel, className }: {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div className={["hg-seg", className ?? ""].filter(Boolean).join(" ")} role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
