import Link from "next/link";
import { cookies } from "next/headers";
import { SearchHero } from "@/components/SearchHero";
import { CodeField } from "@/components/ui/CodeField";
import { Button } from "@/components/ui/Button";
import { Tag } from "@/components/ui/Tag";
import type { Metadata } from "next";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeAlternates, ogLocaleTag } from "@/lib/alternates";
import { withLocale } from "@/lib/localePath";

export async function generateMetadata(): Promise<Metadata> {
  // 首页 SEO 文案随 locale; canonical/hreflang/OG/twitter 全部由首页自持
  // (root layout 只保留全站级 metadata, 不再代管首页的 alternates/openGraph/twitter)
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    // seoTitle 自带品牌名(如 "化工社｜你的AI化学工作台"), 用 absolute 避免再叠 root template 的 ｜品牌 后缀
    title: { absolute: t.brand.seoTitle },
    description: t.brand.seoDesc,
    alternates: localeAlternates("/", locale),
    openGraph: {
      title: t.brand.seoTitle,
      description: t.brand.seoDesc,
      url: withLocale("/", locale),
      siteName: t.brand.name,
      locale: ogLocaleTag(locale),
      type: "website",
      images: [{ url: "/og.png", width: 1200, height: 630, alt: t.brand.ogAlt }],
    },
    twitter: { card: "summary_large_image", title: t.brand.seoTitle, description: t.brand.seoDescShort, images: ["/og.png"] },
  };
}

export default async function Home() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  const authed = (await cookies()).has("hgs_session");
  return (
    <div className="home">
      <section className="hero">
        <h1>{t.home.hero}</h1>
        <p className="hero-subtitle">{t.home.subtitle}</p>
        <SearchHero authed={authed} />
      </section>

      {/* ── AI 接入入口: 第一屏直接给出地址与三条主入口（一级入口钉死为
          MCP / Skills / 工作台 —— tests/test_v170_release_governance.py）。
          ChatGPT / Plugin 状态 = 说明文字 + Tag warn「未上架」（不再是按钮），
          Tag 链到 mcp-guide 的 chatgpt-plugin 锚点。 ── */}
      <section className="home-entry" aria-label={t.home.entryLabel}>
        <CodeField value="https://huagongshe.com/mcp" copyLabel={t.home.entryMcpCopy} className="home-entry-code" />
        <nav className="guide-actions home-entry-actions">
          <Button variant="primary" href={withLocale("/mcp-guide", locale)}>{t.home.entryMcp}</Button>
          <Button variant="secondary" href={withLocale("/skills", locale)}>{t.home.entrySkills}</Button>
          <Button variant="secondary" href={withLocale("/aichem", locale)}>{t.home.entryWorkbench}</Button>
        </nav>
        <p className="home-entry-note">
          {t.home.entryPluginNote}
          <Link href={withLocale("/mcp-guide#chatgpt-plugin", locale)} aria-label={t.home.entryPlugin}>
            <Tag tone="warn">{t.home.pluginNotListed}</Tag>
          </Link>
        </p>
      </section>
    </div>
  );
}
