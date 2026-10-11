"use client";

import { useEffect, useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { Notice } from "@/components/ui/Notice";

/**
 * SlowNotice — IX-4 超时关怀（SMK-018 / FX-16）：客户端加载超过 10s 时
 * 出现「仍在处理，请稍候」Notice（warn）并带「重试」。active=true 起 10s
 * 计时；加载完成（active=false）即消失。重试由调用方重新触发加载。
 */
export function SlowNotice({ active, onRetry }: {
  /** 是否处于加载中（true 期间计时） */
  active: boolean;
  onRetry: () => void;
}) {
  const t = useDictionary();
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) {
      setSlow(false);
      return;
    }
    const timer = setTimeout(() => setSlow(true), 10_000);
    return () => clearTimeout(timer);
  }, [active]);
  if (!slow) return null;
  return (
    <Notice tone="warn" action={{ label: t.common.retry, onClick: onRetry }}>
      {t.common.slowLoading}
    </Notice>
  );
}
