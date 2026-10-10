"use client";

/**
 * RetryNotice — 页面级失败提示 + 「重试」（IX-2：Notice err 附带重试）。
 * 公开主页的反应/笔记区块加载失败时使用；重试 = router.refresh() 重新 SSR。
 */
import { useRouter } from "next/navigation";
import { useDictionary } from "@/components/shared/I18nContext";
import { Notice } from "@/components/ui/Notice";

export function RetryNotice({ children }: { children?: React.ReactNode }) {
  const router = useRouter();
  const t = useDictionary();
  return (
    <Notice tone="err" action={{ label: t.common.retry, onClick: () => router.refresh() }}>
      {children}
    </Notice>
  );
}
