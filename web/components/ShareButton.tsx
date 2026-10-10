"use client";

/**
 * ShareButton — 分享（v1.7 Step 7 支持 iconOnly ghost 图标形态）。
 * navigator.share 退回复制链接；复制成功用 Toast 反馈（图标形态）或
 * 原地文案切换（默认文字形态，guide 页沿用）。
 */
import { useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { Button } from "@/components/ui/Button";
import { IconShare } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";

export function ShareButton({ title, iconOnly = false }: { title?: string; iconOnly?: boolean }) {
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
      if (iconOnly) toast.success(t.guide.shareCopied);
      else { setCopied(true); window.setTimeout(() => setCopied(false), 1800); }
    } catch { /* clipboard blocked */ }
  }
  if (iconOnly) {
    return (
      <Button variant="ghost" iconOnly aria-label={t.guide.share} onClick={() => void share()}>
        <IconShare />
      </Button>
    );
  }
  return <Button variant="secondary" size="sm" onClick={() => void share()}>{copied ? t.guide.shareCopied : t.guide.share}</Button>;
}
