import Link from "next/link";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { EmptyState } from "@/components/ui/EmptyState";

/** 404 页（FX-4 / SMK 遗漏 + IX-8）：ui EmptyState + 两个下一步操作
 *  （返回首页 / 去搜索）。根级（无站点顶栏）；公开路由的带顶栏 404 由
 *  app/(site)/not-found.tsx 同构图提供。 */
export default async function NotFound() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return (
    <div className="app-container">
      <main className="content-page error-page">
        <EmptyState
          title={t.error.notFoundTitle}
          action={{ label: t.error.notFoundAction, href: withLocale("/search", locale) }}
        >
          {t.error.notFoundBody}
        </EmptyState>
        <p className="error-page-home">
          <Link className="text-link" href={withLocale("/", locale)}>{t.error.notFoundHome}</Link>
        </p>
      </main>
    </div>
  );
}
