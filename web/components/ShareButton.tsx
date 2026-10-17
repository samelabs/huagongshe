"use client";

/**
 * ShareButton — 分享（支持 iconOnly ghost 图标形态）。
 * navigator.share 退回复制链接；复制成功用 Toast 反馈（图标形态 / feedback="toast"）
 * 或原地文案切换（默认文字形态，guide 页沿用）。
 * 外观可通过 label/variant/size/className/ariaLabel 覆盖 —— 公开主页
 * 手机端用「分享主页」secondary lg 文字按钮（DESIGN_SYSTEM 6.6），桌面保持 iconOnly。
 */
import { useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { Button, type ButtonVariant, type ButtonSize } from "@/components/ui/Button";
import { IconShare } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";
import { copyText } from "@/lib/clipboard";

export function ShareButton({ url: customUrl, title, iconOnly = false, label, variant, size, className, ariaLabel, feedback = "text", copiedToast }: {
  url?: string;
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
  /** 复制退回时 Toast 文案（默认 t.guide.shareCopied；主页卡片等场景传更具体的「已复制主页链接」） */
  copiedToast?: string;
}) {
  const t = useDictionary();
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = customUrl ?? (typeof window !== "undefined" ? window.location.href : "https://huagongshe.com/guide");
    const shareTitle = title ?? t.guide.title;
    if (navigator.share) {
      try {
        await navigator.share({ title: shareTitle, url });
      } catch { /* 用户取消系统分享面板：不改做复制 */ }
      return;
    }
    if (!(await copyText(url))) { toast.error(t.common.copyFailed); return; }
    if (iconOnly || feedback === "toast") toast.success(copiedToast ?? t.guide.shareCopied);
    else { setCopied(true); window.setTimeout(() => setCopied(false), 1800); }
  }
  if (iconOnly) {
    return (
      <Button variant={variant ?? "ghost"} size={size} iconOnly className={className} aria-label={ariaLabel ?? t.guide.share} onClick={() => void share()}>
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
