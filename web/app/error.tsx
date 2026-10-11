"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { EmptyState } from "@/components/ui/EmptyState";
import { withLocale } from "@/lib/localePath";
import { TextLink } from "@/components/ui/TextLink";

/** 根错误边界（FX-4 / SMK 遗漏）：ui 组件 + 如实文案（客户端渲染出错，
 *  不说「服务暂时不可用」）。根层无站点顶栏 —— 公开页的顶栏保留由
 *  app/(site)/error.tsx 提供；此处给重试 + 返回首页两个出口。 */
export default function ErrorPage({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  const t = useDictionary();
  const locale = useLocale();
  useEffect(() => { if (process.env.NODE_ENV !== "production") console.error(error); }, [error]);
  return (
    <div className="app-container">
      <main className="content-page error-page">
        <EmptyState
          title={t.error.clientTitle}
          action={{ label: t.error.retry, onClick: unstable_retry }}
        >
          {t.error.clientBody}
        </EmptyState>
        <p className="error-page-home">
          <TextLink className="error-page-home-link" href={withLocale("/", locale)}>{t.error.notFoundHome}</TextLink>
        </p>
      </main>
    </div>
  );
}
