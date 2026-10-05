import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
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
      images: [{ url: "/logo.png", width: 512, height: 512, alt: t.brand.ogAlt }],
    },
    twitter: { card: "summary", title: t.brand.seoTitle, description: t.brand.seoDescShort, images: ["/logo.png"] },
  };
}

export default async function Home() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return (
    <div className="home">
      <section className="hero">
        <h1>{t.home.hero}</h1>
        <p className="hero-subtitle">{t.home.subtitle}</p>
        <GlobalSearch />
      </section>

      {/* ── AI 接入入口: 第一屏直接给出地址与三条主入口 ── */}
      <section className="home-entry" aria-label={t.home.entryLabel}>
        <div className="home-entry-mcp">
          <span className="mcp-connect-label">{t.home.entryMcpLabel}</span>
          <code className="mcp-connect-value">https://huagongshe.com/mcp</code>
        </div>
        <nav className="guide-actions">
          <Link className="button primary" href={withLocale("/mcp-guide", locale)}>{t.home.entryMcp}</Link>
          <a className="button secondary" href="/api/agent-guide">{t.home.entryApi}</a>
          <Link className="button secondary" href={withLocale("/skills", locale)}>{t.home.entrySkills}</Link>
          <Link className="button secondary" href={withLocale("/aichem", locale)}>{t.home.entryWorkbench}</Link>
          <Link className="button secondary" href={withLocale("/me/settings/api-tokens", locale)}>{t.home.entryKey}</Link>
        </nav>
      </section>
    </div>
  );
}
