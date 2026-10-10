"use client";

/**
 * Button — v1.7 组件库按钮（docs/design/hgs-ui-reference.html §6）。
 *
 * variant: primary（每区域一个）/ secondary / tonal / ghost / danger / danger-quiet
 * size: sm 32 / md 40（默认）/ lg 48；iconOnly 时按方块渲染（必须给 aria-label）。
 * loading: aria-busy + 转圈 + 宽度锁定（防止文案换成「保存中」时按钮抖动）+ 禁点。
 * href: 渲染为 next/link；asChild: 克隆单个子元素注入按钮类与状态属性。
 */
import { isValidElement, cloneElement, useEffect, useRef } from "react";
import Link from "next/link";

export type ButtonVariant = "primary" | "secondary" | "tonal" | "ghost" | "danger" | "danger-quiet";
export type ButtonSize = "sm" | "md" | "lg";

export type ButtonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 图标按钮：true 时按方块渲染，必须同时传 aria-label（IX-10） */
  iconOnly?: boolean;
  /** 异步进行中：转圈 + 宽度不变 + 禁点 */
  loading?: boolean;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  className?: string;
  children?: React.ReactNode;
  onClick?: (e: React.MouseEvent) => void;
  /** 传了渲染成 next/link（disabled/loading 时退回 button 外观） */
  href?: string;
  /** 克隆 children（单个元素）注入按钮类与状态属性 */
  asChild?: boolean;
  "aria-label"?: string;
};

function classes(p: ButtonProps): string {
  return [
    "hg-btn",
    p.variant ?? "secondary",
    p.size && p.size !== "md" ? p.size : "",
    p.iconOnly ? "icon" : "",
    p.className ?? "",
  ].filter(Boolean).join(" ");
}

/** loading 进入时锁定宽度，退出时解除 */
function useFixedWidthWhileLoading<T extends HTMLElement>(loading: boolean) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (loading) {
      if (!el.style.width) el.style.width = `${el.offsetWidth}px`;
    } else {
      el.style.width = "";
    }
  }, [loading]);
  return ref;
}

export function Button(props: ButtonProps) {
  const { variant, size, iconOnly, loading = false, disabled, className, children, onClick, asChild, href, type, ...rest } = props;

  if (process.env.NODE_ENV !== "production" && iconOnly && !rest["aria-label"]) {
    console.error("<Button iconOnly> requires an aria-label");
  }

  const ref = useFixedWidthWhileLoading<HTMLButtonElement & HTMLAnchorElement>(loading);
  const stateProps = {
    "aria-busy": loading || undefined,
    "aria-disabled": loading || disabled || undefined,
  };

  if (asChild && isValidElement(children)) {
    const child = children as React.ReactElement<Record<string, unknown>>;
    const merged = `${classes(props)}${typeof child.props.className === "string" ? ` ${child.props.className}` : ""}`;
    return cloneElement(child, {
      ...stateProps,
      ...(loading || disabled ? { "aria-disabled": true as const, href: undefined, onClick: undefined } : {}),
      ...child.props,
      className: merged,
    });
  }

  if (href && !disabled && !loading) {
    return (
      <Link href={href} className={classes(props)} onClick={onClick} ref={ref} {...stateProps} {...rest}>
        {loading && <i className="hg-spin" aria-hidden="true" />}
        {children}
      </Link>
    );
  }

  return (
    <button
      type={type ?? "button"}
      className={classes(props)}
      // loading 不落 disabled 属性：disabled 会把按钮染成灰色
      // （.hg-btn:disabled），loading 必须保持原 variant 颜色 + 转圈
      // + cursor:progress（见 ui.css [aria-busy] 规则）。点击与键盘触发
      // 由 onClick 守卫拦下，aria-disabled 播报状态。
      disabled={disabled || undefined}
      onClick={loading || disabled ? undefined : onClick}
      ref={ref}
      {...stateProps}
      {...rest}
    >
      {loading && <i className="hg-spin" aria-hidden="true" />}
      {children}
    </button>
  );
}
