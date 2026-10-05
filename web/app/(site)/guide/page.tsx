import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";
import { ShareButton } from "@/components/ShareButton";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return {
    title: t.guide.title,
    description: t.guide.desc,
  };
}

export default async function GuidePage() {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return <div className="content-page guide-page">
    <header className="page-head guide-hero">
      <div className="guide-hero-top">
        <p className="page-kicker">GUIDE</p>
        <ShareButton />
      </div>
      <h1>{t.guide.hero}</h1>
      <p>{t.guide.heroBody}</p>
    </header>

    {/* ── 接入入口: 第一屏直出 MCP 地址 / AI Key ── */}
    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.guide.connectKicker}</p></div></div>
      <div className="mcp-connect">
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.guide.connectMcpLabel}</span>
          <code className="mcp-connect-value">https://huagongshe.com/mcp</code>
        </div>
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.guide.connectKeyLabel}</span>
          <code className="mcp-connect-value">Authorization: Bearer &lt;AI Key&gt;</code>
        </div>
        <p className="mcp-connect-desc">{t.guide.connectKeyDesc}</p>
        <div className="guide-actions">
          <Link className="button primary" href={withLocale("/mcp-guide", locale)}>{t.guide.mcpCta}</Link>
          <Link className="button secondary" href="/me/settings/api-tokens">{t.guide.keyCta}</Link>
        </div>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.guide.capabilityKicker}</p></div></div>
      <div className="guide-cards">
        <article className="guide-card">
          <h3>{t.guide.cap1Title}</h3>
          <p>{t.guide.cap1Desc}</p>
        </article>
        <article className="guide-card">
          <h3>{t.guide.cap2Title}</h3>
          <p>{t.guide.cap2Desc}</p>
          {t.guide.cap2Badge ? <span className="guide-card-badge">{t.guide.cap2Badge}</span> : null}
        </article>
        <article className="guide-card">
          <h3>{t.guide.cap3Title}</h3>
          <p>{t.guide.cap3Desc}</p>
          <span className="guide-card-badge">{t.guide.cap3Badge}</span>
        </article>
        <article className="guide-card">
          <h3>{t.guide.cap4Title}</h3>
          <p>{t.guide.cap4Desc}</p>
          <span className="guide-card-badge">{t.guide.cap4Badge}</span>
        </article>
      </div>
    </section>

    <section className="guide-section">
      <div className="guide-fallback">
        <h4>{t.guide.fallbackTitle}</h4>
        <p>{t.guide.fallbackDesc}</p>
        <AiSubmissionPrompt />
      </div>
    </section>

    <section className="guide-section guide-trust">
      <div className="section-heading"><div><p className="page-kicker">{t.guide.trustKicker}</p></div></div>
      <ul className="guide-trust-list">
        <li>{t.guide.trust1}</li>
        <li>{t.guide.trust2}</li>
        <li>{t.guide.trust3}</li>
      </ul>
    </section>
  </div>;
}
