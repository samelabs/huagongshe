"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { EmptyState } from "@/components/ui/EmptyState";
import { withLocale } from "@/lib/localePath";
import { TextLink } from "@/components/ui/TextLink";

/** 工作台错误边界(/ SMK 遗漏）：ui 组件 + 如实文案 + 重试；
 * 旧类名 wb-btn 与英文 eyebrow 一并清除。 */
export default function WorkbenchError({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  const t = useDictionary();
  const locale = useLocale();
  useEffect(() => { if (process.env.NODE_ENV !== "production") console.error(error); }, [error]);
  return (
    <section className="wb-state wb-state-error">
      <EmptyState
        title={t.error.clientTitle}
        action={{ label: t.error.retry, onClick: unstable_retry }}
      >
        {t.error.clientBody}
      </EmptyState>
      <p className="error-page-home">
        <TextLink className="error-page-home-link" href={withLocale("/", locale)}>{t.error.notFoundHome}</TextLink>
      </p>
    </section>
  );
}
