import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";
import { ShareButton } from "@/components/ShareButton";
import { CodeField } from "@/components/ui/CodeField";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeAlternates } from "@/lib/alternates";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    title: t.guide.title,
    description: t.guide.desc,
    alternates: localeAlternates("/guide", locale),
  };
}

/** 文档页（§9.6，Step 11）：阅读版式 --w-reading 720；段落 + 小标题为主，
 *  代码/配置片段走 CodeField（IX-7 复制播报），无英文 eyebrow（同 Step 10 A3）。 */
export default async function GuidePage() {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return <div className="content-page guide-page">
    <header className="page-head guide-hero">
      <div className="guide-hero-top">
        <ShareButton />
      </div>
      <h1>{t.guide.hero}</h1>
      <p>{t.guide.heroBody}</p>
    </header>

    {/* ── 接入入口: 第一屏直出 MCP 地址 / AI Key ── */}
    <section className="guide-section">
      <div className="section-heading"><div><h2>{t.guide.connectKicker}</h2></div></div>
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
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><h2>{t.guide.capabilityKicker}</h2></div></div>
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
    </section>

    <section className="guide-section">
      <h2>{t.guide.fallbackTitle}</h2>
      <p className="guide-section-intro">{t.guide.fallbackDesc}</p>
      <AiSubmissionPrompt />
    </section>

    <section className="guide-section guide-trust">
      <div className="section-heading"><div><h2>{t.guide.trustKicker}</h2></div></div>
      <ul className="guide-trust-list">
        <li>{t.guide.trust1}</li>
        <li>{t.guide.trust2}</li>
        <li>{t.guide.trust3}</li>
      </ul>
    </section>
  </div>;
}
