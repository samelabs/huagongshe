import Link from "next/link";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { EmptyState } from "@/components/ui/EmptyState";

/** 公开路由 404（FX-4，新增）：notFound() 在 (site) 段内抛出时落到这里 ——
 *  站点顶栏/页脚保留（(site) layout 继续渲染），用户不会落到没有导航的空白页。 */
export default async function SiteNotFound() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return (
    <div className="content-page error-page">
      <EmptyState
        title={t.error.notFoundTitle}
        action={{ label: t.error.notFoundAction, href: withLocale("/search", locale) }}
      >
        {t.error.notFoundBody}
      </EmptyState>
      <p className="error-page-home">
        <Link className="text-link" href={withLocale("/", locale)}>{t.error.notFoundHome}</Link>
      </p>
    </div>
  );
}
