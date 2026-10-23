import { SearchHero } from "@/components/shared/SearchHero";
import { CodeField } from "@/components/ui/CodeField";
import { Button } from "@/components/ui/Button";
import { PageFrame } from "@/components/ui/PageFrame";
import { Tag } from "@/components/ui/Tag";
import type { Metadata } from "next";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeCanonical, ogLocaleTag } from "@/lib/alternates";
import { withLocale } from "@/lib/localePath";

/** 随代码部署的 Agent Plugin 下载包（scripts/build_plugin_package.py 产物） */
const PLUGIN_PACKAGE_URL = "/downloads/huagongshe-agent-plugin-1.0.0.zip";

import { buildShareMetadata } from "@/lib/shareMeta";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const shareMeta = buildShareMetadata({
    title: t.brand.seoTitle,
    description: t.brand.seoDesc,
    path: "/",
    locale,
    siteName: t.brand.name,
    ogImage: {
      url: "/og.png",
      width: 1200,
      height: 630,
      alt: t.brand.ogAlt,
    },
    twitterCard: "summary_large_image",
  });
  return {
    title: { absolute: t.brand.seoTitle },
    description: t.brand.seoDesc,
    alternates: localeCanonical("/", locale),
    ...shareMeta,
  };
}

export default async function Home() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return (
    <PageFrame className="home">
      {/* 标题与搜索区按现行规则在框内居中 */}
      <section className="hero">
        <h1>{t.home.hero}</h1>
        <p className="hero-subtitle">{t.home.subtitle}</p>
        <SearchHero />
      </section>

      {/* ── AI 接入入口: 第一屏直接给出地址与主入口 MCP / Skills /
          Agent Plugin。地址胶囊即语义，独立小标签撤除（section 的
          aria-label 保留无障碍命名）。Agent Plugin 直接下载随代码部署的
          插件包（web/public/downloads，见 scripts/build_plugin_package.py）。 ── */}
      <section className="home-entry-section" aria-label={t.home.entryLabel}>
        <div className="home-entry">
          <CodeField value="https://huagongshe.com/mcp" copyLabel={t.home.entryMcpCopy} className="home-entry-code" />
          <nav className="guide-actions home-entry-actions">
            <Button variant="primary" href={withLocale("/mcp-guide", locale)}>{t.home.entryMcp}</Button>
            <Button variant="secondary" href={withLocale("/skills", locale)}>{t.home.entrySkills}</Button>
            <Button variant="secondary" href={PLUGIN_PACKAGE_URL} download>
              {t.home.entryPlugin}
            </Button>
          </nav>
        </div>
      </section>
    </PageFrame>
  );
}
