/* ── 治理严重度呈现契约 ────────────────────────────────────
   严重度定义(高/中/低)不变; 是否"激活"告警色只由原始数据结构决定,
   严禁解析格式化后的 val 字符串(如 "0/3,000"、"暂不可用")。
     · exact 数值: value > 0
     · sample   : matched > 0
     · unavailable / deferred: active = false
     · 0        : active = false
   active=true 保留 high/mid severity color; active=false → quiet/neutral。 */

export type SeverityState = {
  /** 原始数据是否可用(unavailable / deferred → false) */
  available: boolean;
  /** 当前是否存在真实异常(0 与 unavailable → false) */
  active: boolean;
};

export const INACTIVE: SeverityState = { available: false, active: false };

/** 治理 section 原始载荷的最小形状(与 A2 契约一致) */
export type RawSection = { available?: boolean; mode?: string; value?: unknown } | null | undefined;

/** 直方计数(exact) → 状态 */
export function statusFromCount(n: unknown): SeverityState {
  if (typeof n !== "number" || Number.isNaN(n)) return { ...INACTIVE };
  return { available: true, active: n > 0 };
}

/** 治理 section 原始载荷 → 状态: number → value>0; sample payload → matched>0 */
export function statusFromSection(sec: RawSection): SeverityState {
  if (!sec || sec.available !== true || sec.mode === "deferred") return { ...INACTIVE };
  const v = sec.value as { matched?: unknown } | null | undefined;
  if (typeof v === "number") return { available: true, active: v > 0 };
  if (v && typeof v.matched === "number") return { available: true, active: v.matched > 0 };
  return { available: true, active: false };
}

/** 仅"当前存在真实异常"时激活严重度颜色, 否则 neutral */
export function severityClass(sev: string, active: boolean): "bad" | "warn" | "quiet" {
  if (!active) return "quiet";
  return sev === "高" ? "bad" : "warn";
}
