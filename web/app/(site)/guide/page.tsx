import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";
import { ShareButton } from "@/components/ShareButton";
import t from "@/lib/i18n";

export const metadata: Metadata = {
  title: t.guide.title,
  description: t.guide.desc,
};

export default function GuidePage() {
  return <div className="content-page guide-page">
    <header className="page-head guide-hero">
      <div className="guide-hero-top">
        <p className="page-kicker">GUIDE</p>
        <ShareButton />
      </div>
      <h1>{t.guide.hero}</h1>
      <p>{t.guide.heroBody}</p>
    </header>

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
          <span className="guide-card-badge">{t.guide.cap2Badge}</span>
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
      <div className="section-heading"><div><p className="page-kicker">{t.guide.startKicker}</p></div></div>
      <div className="guide-paths">
        <article className="guide-path">
          <div className="guide-path-head">
            <h3>{t.guide.path1Title}</h3>
            <span className="guide-path-suit">{t.guide.path1Suit}</span>
          </div>
          <p>{t.guide.path1Desc}</p>
          <div className="guide-actions">
            <Link className="button primary" href="/mcp-guide">{t.guide.mcpCta}</Link>
          </div>
        </article>
        <article className="guide-path">
          <div className="guide-path-head">
            <h3>{t.guide.path2Title}</h3>
            <span className="guide-path-suit">{t.guide.path2Suit}</span>
          </div>
          <p>{t.guide.path2Desc}</p>
          <AiSubmissionPrompt />
        </article>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.guide.refKicker}</p></div></div>
      <p className="guide-ref-intro">{t.guide.refIntro}</p>
      <table className="guide-ref-table">
        <tbody>
          <tr>
            <td className="guide-ref-name"><code>{t.guide.refLlmsTxt}</code></td>
            <td className="guide-ref-desc">{t.guide.refLlmsTxtDesc}</td>
            <td className="guide-ref-link"><a href="/llms.txt">{t.guide.refView}</a></td>
          </tr>
          <tr>
            <td className="guide-ref-name"><code>{t.guide.refAgentGuide}</code></td>
            <td className="guide-ref-desc">{t.guide.refAgentGuideDesc}</td>
            <td className="guide-ref-link"><a href="/api/agent-guide">{t.guide.refView}</a></td>
          </tr>
          <tr>
            <td className="guide-ref-name"><code>{t.guide.refSkill}</code></td>
            <td className="guide-ref-desc">{t.guide.refSkillDesc}</td>
            <td className="guide-ref-link"><a href="/skills/huagongshe-reaction-publisher/SKILL.md" download>{t.guide.refDownload}</a></td>
          </tr>
        </tbody>
      </table>
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
