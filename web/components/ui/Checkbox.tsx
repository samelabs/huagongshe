"use client";

/**
 * Checkbox — 复选框（DESIGN_SYSTEM 3.3 表单控件）。
 * 原生 input[type=checkbox] 承载语义与键盘操作，外观走 token；
 * 文字部分可选，整体是 label，点击文字即切换。
 */
import type { ReactNode } from "react";

export function Checkbox({ label, className, ...rest }:
  React.InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode; ref?: React.Ref<HTMLInputElement> }) {
  return (
    <label className={["hg-check", className ?? ""].filter(Boolean).join(" ")}>
      <input type="checkbox" {...rest} />
      {label}
    </label>
  );
}
