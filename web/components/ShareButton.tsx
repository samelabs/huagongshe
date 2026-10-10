"use client";

/**
 * ShareButton — 分享（v1.7 Step 7 支持 iconOnly ghost 图标形态）。
 * navigator.share 退回复制链接；复制成功用 Toast 反馈（图标形态 / feedback="toast"）
 * 或原地文案切换（默认文字形态，guide 页沿用）。
 * Step 10 Part E：label/variant/size/className/ariaLabel 可覆盖 —— 公开主页
 * 手机端用「分享主页」secondary lg 文字按钮（§12 第三屏），桌面保持 iconOnly。
 */
import { useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { Button, type ButtonVariant, type ButtonSize } from "@/components/ui/Button";
import { IconShare } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";

export function ShareButton({ title, iconOnly = false, label, variant, size, className, ariaLabel, feedback = "text" }: {
  title?: string;
  iconOnly?: boolean;
  /** 文字按钮文案（默认 t.guide.share） */
  label?: string;
  /** 图标形态默认 ghost、文字形态默认 secondary（guide 页沿用） */
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  /** 无障碍名（默认 t.guide.share） */
  ariaLabel?: string;
  /** 文字形态的复制反馈：text 原地切换「已复制」（默认）；toast 弹 Toast 不变文案 */
  feedback?: "text" | "toast";
}) {
  const t = useDictionary();
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = typeof window !== "undefined" ? window.location.href : "https://huagongshe.com/guide";
    const shareTitle = title ?? t.guide.title;
    if (navigator.share) {
      try {
        await navigator.share({ title: shareTitle, url });
        return;
      } catch { /* user cancelled, fall through to copy */ }
    }
    try {
      await navigator.clipboard.writeText(url);
      if (iconOnly || feedback === "toast") toast.success(t.guide.shareCopied);
      else { setCopied(true); window.setTimeout(() => setCopied(false), 1800); }
    } catch { /* clipboard blocked */ }
  }
  if (iconOnly) {
    return (
      <Button variant={variant ?? "ghost"} iconOnly className={className} aria-label={ariaLabel ?? t.guide.share} onClick={() => void share()}>
        <IconShare />
      </Button>
    );
  }
  return (
    <Button variant={variant ?? "secondary"} size={size ?? "sm"} className={className} aria-label={ariaLabel} onClick={() => void share()}>
      {feedback === "text" && copied ? t.guide.shareCopied : label ?? t.guide.share}
    </Button>
  );
}
