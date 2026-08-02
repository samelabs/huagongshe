import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";
import t from "@/lib/i18n";

export const metadata: Metadata = {
  title: t.guide.title,
  description: t.guide.desc,
};

export default function GuidePage() {
  return <div className="content-page guide-page">
    <header className="guide-hero">
      <p className="page-kicker">GUIDE</p>
      <h1>{t.guide.hero}</h1>
      <p>{t.guide.heroBody}</p>
      <div className="guide-security-note"><strong>{t.guide.securityNote}</strong><span>{t.guide.securityDetail}</span></div>
      <div className="guide-actions">
        <Link className="button primary" href="/me/settings/api-tokens">{t.guide.setupCta}</Link>
      </div>
    </header>

    <section className="guide-section">
      <div className="section-heading"><div><p>{t.guide.stepsKicker}</p><h2>{t.guide.stepsTitle}</h2></div></div>
      <ol className="guide-steps">
        <li><strong>{t.guide.step1Title}</strong><span>{t.guide.step1Desc}</span></li>
        <li><strong>{t.guide.step2Title}</strong><span>{t.guide.step2Desc}</span></li>
        <li><strong>{t.guide.step3Title}</strong><span>{t.guide.step3Desc}</span></li>
      </ol>
    </section>

    <section className="guide-section guide-ai-section">
      <div className="section-heading"><div><p>{t.guide.copyKicker}</p><h2>{t.guide.copyTitle}</h2></div></div>
      <p className="guide-lead">{t.guide.copyBody}</p>
      <AiSubmissionPrompt />
    </section>

    <details className="guide-section technical-guide">
      <summary>{t.guide.techKicker}</summary>
      <div className="technical-guide-content">
        <div>
          <h2>{t.guide.techTitle}</h2>
          <p>{t.guide.techBody}</p>
        </div>
        <div className="guide-actions">
          <a className="button secondary small" href="/skills/huagongshe-reaction-publisher/SKILL.md" download>{t.guide.downloadSkill}</a>
          <a className="button secondary small" href="/api/agent-guide" target="_blank" rel="noreferrer">{t.guide.viewApi}</a>
        </div>
      </div>
    </details>

    <section className="guide-section ownership-guide">
      <div className="section-heading"><div><p>{t.guide.principlesTitle}</p><h2>{t.guide.principlesSubtitle}</h2></div></div>
      <div className="guide-principles">
        <article><strong>{t.guide.p1Title}</strong><p>{t.guide.p1Body}</p></article>
        <article><strong>{t.guide.p2Title}</strong><p>{t.guide.p2Body}</p></article>
        <article><strong>{t.guide.p3Title}</strong><p>{t.guide.p3Body}</p></article>
      </div>
    </section>
  </div>;
}
