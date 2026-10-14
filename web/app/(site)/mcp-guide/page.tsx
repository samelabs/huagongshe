"use client";

import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { CodeField } from "@/components/ui/CodeField";

const PLUGIN_PACKAGE_URL = "/downloads/huagongshe-agent-plugin-1.0.0.zip";

/** 文档页（6.10）：阅读版式 --w-reading 720；配置片段走 CodeField
 *  multiline（IX-7：复制 aria-live 播报 + ✓ 1.5s，内部滚动不撑破布局）。 */
function AgentSteps({ title, desc, steps }: { title: string; desc: string; steps: readonly string[] }) {
  return <div className="guide-prose-list">
    <h3>{title}</h3>
    <p>{desc}</p>
    <ol className="mcp-agent-steps">
      {steps.map((step, i) => <li key={i}>{step}</li>)}
    </ol>
  </div>;
}

export default function McpPage() {
  const t = useDictionary();
  const locale = useLocale();
  return <div className="content-page guide-page mcp-page">
    <Breadcrumb
      items={[
        { label: t.chemical.home, href: withLocale("/", locale) },
        { label: t.mcp.hero },
      ]}
      ariaLabel={t.common.breadcrumb}
    />
    <header className="page-head guide-hero">
      <h1>{t.mcp.hero}</h1>
      <p>{t.mcp.heroBody}</p>
    </header>

    {/* Agent Plugin：agent-plugins.org 规范插件包下载入口，MCP 端点只在下方出现一次（I-005） */}
    <section className="guide-section" id="agent-plugin">
      <div className="section-heading"><div><h2>{t.mcp.pluginTitle}</h2></div></div>
      <p className="guide-section-intro">{t.mcp.pluginStatus}</p>
      <div className="guide-actions">
        <Button variant="secondary" href={PLUGIN_PACKAGE_URL} download>
          {t.mcp.pluginDownload}
        </Button>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><h2>{t.mcp.connectKicker}</h2></div></div>
      <div className="mcp-connect">
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectUrlLabel}</span>
          <CodeField value="https://huagongshe.com/mcp" />
        </div>
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectAnonLabel}</span>
          <p className="mcp-connect-text">{t.mcp.connectAnonDesc}</p>
        </div>
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectOauthLabel}</span>
          <p className="mcp-connect-text">{t.mcp.connectOauthDesc}</p>
        </div>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><h2>{t.mcp.connectCompatKicker}</h2></div></div>
      <div className="mcp-connect">
        <div className="mcp-connect-row">
          <span className="mcp-connect-label">{t.mcp.connectTokenLabel}</span>
          <CodeField value="Authorization: Bearer <AI Key>" />
        </div>
        <p className="mcp-connect-desc">{t.mcp.connectTokenDesc}</p>
        <div className="guide-actions">
          <Link className="hg-btn secondary" href={withLocale("/me/settings/api-tokens", locale)}>{t.mcp.connectTokenCta}</Link>
        </div>
      </div>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><h2>{t.mcp.commonKicker}</h2></div></div>
      <p className="guide-section-intro">{t.mcp.commonDesc}</p>
      <CodeField value={t.mcp.commonJson} multiline />
      <p className="guide-section-intro">{t.mcp.compatJsonDesc}</p>
    </section>

    <section className="guide-section">
      <div className="section-heading"><div><h2>{t.mcp.toolsKicker}</h2></div></div>
      <p className="guide-section-intro">{t.mcp.toolsIntro}</p>
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
      <div className="section-heading"><div><h2>{t.mcp.agentsKicker}</h2></div></div>
      <div className="guide-agent-stack">
        <AgentSteps title={t.mcp.qwenTitle} desc={t.mcp.qwenDesc} steps={t.mcp.qwenSteps} />
        <AgentSteps title={t.mcp.workbuddyTitle} desc={t.mcp.workbuddyDesc} steps={t.mcp.workbuddySteps} />
        <AgentSteps title={t.mcp.doubaoTitle} desc={t.mcp.doubaoDesc} steps={t.mcp.doubaoSteps} />
      </div>
    </section>

    <section className="guide-section guide-trust">
      <div className="section-heading"><div><h2>{t.mcp.trustKicker}</h2></div></div>
      <ul className="guide-trust-list">
        <li>{t.mcp.trust1}</li>
        <li>{t.mcp.trust2}</li>
        <li>{t.mcp.trust3}</li>
        <li>{t.mcp.trust4}</li>
      </ul>
    </section>
  </div>;
}
