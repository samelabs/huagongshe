"use client";

import { useState } from "react";
import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

function CopyJson() {
  const t = useDictionary();
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(t.mcp.commonJson);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  return <div className="prompt-box">
    <pre>{t.mcp.commonJson}</pre>
    <button type="button" className="button secondary small" onClick={copy}>
      {t.mcp.copyJson(copied)}
    </button>
  </div>;
}

function AgentCard({ title, desc, steps }: { title: string; desc: string; steps: readonly string[] }) {
  return <article className="guide-card mcp-agent-card">
    <h3>{title}</h3>
    <p>{desc}</p>
    <ol className="mcp-agent-steps">
      {steps.map((step, i) => <li key={i}>{step}</li>)}
    </ol>
  </article>;
}

export default function McpPage() {
  const t = useDictionary();
  const locale = useLocale();
  return <div className="content-page guide-page mcp-page">
    <header className="page-head guide-hero">
      <div className="guide-hero-top">
        <p className="page-kicker">MCP</p>
      </div>
      <h1>{t.mcp.hero}</h1>
      <p>{t.mcp.heroBody}</p>
    </header>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.mcp.connectKicker}</p></div></div>
      <div className="mcp-connect">
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectUrlLabel}</span>
          <code className="mcp-connect-value">https://huagongshe.com/mcp</code>
        </div>
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectAnonLabel}</span>
          <span className="mcp-connect-value">{t.mcp.connectAnonDesc}</span>
        </div>
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectOauthLabel}</span>
          <span className="mcp-connect-value">{t.mcp.connectOauthDesc}</span>
        </div>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.mcp.connectCompatKicker}</p></div></div>
      <div className="mcp-connect">
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectTokenLabel}</span>
          <code className="mcp-connect-value">Authorization: Bearer &lt;AI Key&gt;</code>
        </div>
        <p className="mcp-connect-desc">{t.mcp.connectTokenDesc}</p>
        <div className="guide-actions">
          <Link className="button secondary" href={withLocale("/me/settings/api-tokens", locale)}>{t.mcp.connectTokenCta}</Link>
        </div>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.mcp.commonKicker}</p></div></div>
      <p className="guide-ref-intro">{t.mcp.commonDesc}</p>
      <CopyJson />
      <p className="guide-ref-intro">{t.mcp.compatJsonDesc}</p>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.mcp.toolsKicker}</p></div></div>
      <p className="guide-ref-intro">{t.mcp.toolsIntro}</p>
      <table className="guide-ref-table mcp-tools-table">
        <tbody>
          {t.mcp.tools.map((tool) => (
            <tr key={tool.name}>
              <td className="guide-ref-name"><code>{tool.name}</code></td>
              <td className="mcp-tool-auth">{tool.auth}</td>
              <td className="guide-ref-desc">{tool.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><p className="page-kicker">{t.mcp.agentsKicker}</p></div></div>
      <div className="guide-cards mcp-agents">
        <AgentCard title={t.mcp.qwenTitle} desc={t.mcp.qwenDesc} steps={t.mcp.qwenSteps} />
        <AgentCard title={t.mcp.workbuddyTitle} desc={t.mcp.workbuddyDesc} steps={t.mcp.workbuddySteps} />
        <AgentCard title={t.mcp.doubaoTitle} desc={t.mcp.doubaoDesc} steps={t.mcp.doubaoSteps} />
      </div>
    </section>

    <section className="guide-section guide-trust">
      <div className="section-heading"><div><p className="page-kicker">{t.mcp.trustKicker}</p></div></div>
      <ul className="guide-trust-list">
        <li>{t.mcp.trust1}</li>
        <li>{t.mcp.trust2}</li>
        <li>{t.mcp.trust3}</li>
        <li>{t.mcp.trust4}</li>
      </ul>
    </section>
  </div>;
}
