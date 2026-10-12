"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { EmptyState } from "@/components/ui/EmptyState";
import { withLocale } from "@/lib/localePath";
import { TextLink } from "@/components/ui/TextLink";

/** 公开页错误边界（FX-4 / SMK 遗漏，新增）：公开页面出错时保留站点顶栏
 *  （本文件渲染在 (site) layout 内，SiteHeader/footer 不丢），ui 组件 +
 *  如实文案 + 重试/返回首页。 */
export default function SiteError({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  const t = useDictionary();
  const locale = useLocale();
  useEffect(() => { if (process.env.NODE_ENV !== "production") console.error(error); }, [error]);
  return (
    <div className="content-page error-page">
      <EmptyState
        title={t.error.clientTitle}
        action={{ label: t.error.retry, onClick: unstable_retry }}
      >
        {t.error.clientBody}
      </EmptyState>
      <p className="error-page-home">
        <TextLink className="error-page-home-link" href={withLocale("/", locale)}>{t.error.notFoundHome}</TextLink>
      </p>
    </div>
  );
}
