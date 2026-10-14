"use client";

import { useEffect } from "react";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { EmptyState } from "@/components/ui/EmptyState";
import { withLocale } from "@/lib/localePath";
import { TextLink } from "@/components/ui/TextLink";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { SiteFooter } from "@/components/shell/SiteFooter";

/** 根错误边界（DESIGN_SYSTEM 4.1）：外壳完整（SiteHeader + SiteFooter）。
 *  EmptyState + “重新加载”；文案说明数据未丢失、可重试，不暴露技术细节。 */
export default function ErrorPage({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  const t = useDictionary();
  const locale = useLocale();
  useEffect(() => { if (process.env.NODE_ENV !== "production") console.error(error); }, [error]);
  return (
    <div className="app-container">
      <SiteHeader />
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
      <SiteFooter />
    </div>
  );
}
