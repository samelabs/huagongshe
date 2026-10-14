import type { Metadata } from "next";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { EmptyState } from "@/components/ui/EmptyState";
import { TextLink } from "@/components/ui/TextLink";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { SiteFooter } from "@/components/shell/SiteFooter";

/** 404 有自己的 title（layout 模板补 ｜品牌）。 */
export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.error.notFoundTitle };
}

/** 404 页（DESIGN_SYSTEM 2.3 / 4.1）：任何 404 都有完整外壳（SiteHeader + SiteFooter）。
 *  未匹配路由（如 /zh-CN/xxx）也带顶栏和页脚。
 *  EmptyState 标题取 error.notFoundTitle，两个出口：去查询（tonal）+ 返回首页（TextLink）。 */
export default async function NotFound() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return (
    <div className="app-container">
      <SiteHeader />
      <main className="content-page error-page">
        <EmptyState
          title={t.error.notFoundTitle}
          action={{ label: t.error.notFoundAction, href: withLocale("/search", locale) }}
        >
          {t.error.notFoundBody}
        </EmptyState>
        <p className="error-page-home">
          <TextLink className="error-page-home-link" href={withLocale("/", locale)}>{t.error.notFoundHome}</TextLink>
        </p>
      </main>
      <SiteFooter />
    </div>
  );
}
