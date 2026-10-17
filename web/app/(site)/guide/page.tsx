import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";
import { ShareButton } from "@/components/ShareButton";
import { CodeField } from "@/components/ui/CodeField";
import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeAlternates } from "@/lib/alternates";

import { buildShareMetadata } from "@/lib/shareMeta";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const shareMeta = buildShareMetadata({
    title: `${t.guide.title}｜${t.brand.name}`,
    description: t.guide.desc,
    path: "/guide",
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
    title: t.guide.title,
    description: t.guide.desc,
    alternates: localeAlternates("/guide", locale),
    ...shareMeta,
  };
}

/** 文档页（6.10）：阅读版式 --w-reading 720；段落 + 小标题为主，
 * 代码/配置片段走 CodeField(复制播报），无英文 eyebrow。 */
export default async function GuidePage() {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return <PageFrame tier="reading" className="guide-page">
    <PageHead
      breadcrumb={[
        { label: t.chemical.home, href: withLocale("/", locale) },
        { label: t.guide.title },
      ]}
      title={t.guide.hero}
      subtitle={t.guide.heroBody}
      actions={<ShareButton />}
    />

    {/* ── 接入入口: 第一屏直出 MCP 地址 / AI Key ── */}
    <Section title={t.guide.connectKicker}>
      <div className="mcp-connect">
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.guide.connectMcpLabel}</span>
          <CodeField value="https://huagongshe.com/mcp" />
        </div>
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.guide.connectKeyLabel}</span>
          <CodeField value="Authorization: Bearer <AI Key>" />
        </div>
        <p className="mcp-connect-desc">{t.guide.connectKeyDesc}</p>
        <div className="guide-actions">
          <Link className="hg-btn primary" href={withLocale("/mcp-guide", locale)}>{t.guide.mcpCta}</Link>
          <Link className="hg-btn secondary" href={withLocale("/me/settings/api-tokens", locale)}>{t.guide.keyCta}</Link>
        </div>
      </div>
    </Section>

    <Section title={t.guide.capabilityKicker}>
      <div className="guide-prose-list">
        <h3>{t.guide.cap1Title}</h3>
        <p>{t.guide.cap1Desc}</p>
        <h3>{t.guide.cap2Title}{t.guide.cap2Badge ? <> <span className="guide-inline-badge">{t.guide.cap2Badge}</span></> : null}</h3>
        <p>{t.guide.cap2Desc}</p>
        <h3>{t.guide.cap3Title} <span className="guide-inline-badge">{t.guide.cap3Badge}</span></h3>
        <p>{t.guide.cap3Desc}</p>
        <h3>{t.guide.cap4Title} <span className="guide-inline-badge">{t.guide.cap4Badge}</span></h3>
        <p>{t.guide.cap4Desc}</p>
      </div>
    </Section>

    <Section title={t.guide.fallbackTitle} description={t.guide.fallbackDesc}>
      <AiSubmissionPrompt />
    </Section>

    <Section title={t.guide.trustKicker}>
      <ul className="guide-trust-list">
        <li>{t.guide.trust1}</li>
        <li>{t.guide.trust2}</li>
        <li>{t.guide.trust3}</li>
      </ul>
    </Section>
  </PageFrame>;
}
