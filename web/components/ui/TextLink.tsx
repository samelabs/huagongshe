"use client";

/**
 * TextLink — 行内文字链接 / 文字按钮（§6；BX-B1）。
 *
 * 旧类 text-link / text-button 的唯一 ui 归宿：href → next/link，
 * onClick → button。语义色 = --action，无底无边框，hover 下划线。
 * 行内排版尺寸跟上下文（fs-13/14 由使用处继承或指定），不承担块级动作
 * —— 主要动作永远用 Button。
 */
import Link from "next/link";

export function TextLink({ href, onClick, disabled, type, className, children, "aria-label": ariaLabel, ariaExpanded, ariaControls }: {
  /** 传了渲染 next/link；不传渲染 button（文字按钮） */
  href?: string;
  onClick?: (e: React.MouseEvent) => void;
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
  className?: string;
  children?: React.ReactNode;
  "aria-label"?: string;
  ariaExpanded?: boolean;
  ariaControls?: string;
}) {
  const cls = ["hg-text", className].filter(Boolean).join(" ");
  if (href && !disabled) {
    return <Link href={href} className={cls} aria-label={ariaLabel}>{children}</Link>;
  }
  return (
    <button
      type={type ?? "button"}
      className={cls}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-expanded={ariaExpanded}
      aria-controls={ariaControls}
    >
      {children}
    </button>
  );
}
