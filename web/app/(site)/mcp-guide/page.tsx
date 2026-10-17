"use client";

import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { CodeField } from "@/components/ui/CodeField";
import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";

const PLUGIN_PACKAGE_URL = "/downloads/huagongshe-agent-plugin-1.0.0.zip";

/** 文档页（6.10）：阅读版式 --w-reading 720；配置片段走 CodeField
 * multiline（复制 aria-live 播报 + ✓ 1.5s，内部滚动不撑破布局）。 */
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
  return <>
    <PageFrame tier="reading" className="guide-page mcp-page">
      <PageHead
        breadcrumb={[
          { label: t.chemical.home, href: withLocale("/", locale) },
          { label: t.mcp.hero },
        ]}
        title={t.mcp.hero}
        subtitle={t.mcp.heroBody}
      />

      <Section title={t.mcp.connectKicker}>
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
      </Section>

      <Section title={t.mcp.connectCompatKicker}>
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
      </Section>

      {/* Agent Plugin：agent-plugins.org 规范插件包下载入口，MCP 端点只在下方出现一次 */}
      <Section id="agent-plugin" title={t.mcp.pluginTitle} description={t.mcp.pluginStatus}>
        <div className="guide-actions">
          <Button variant="secondary" href={PLUGIN_PACKAGE_URL} download>
            {t.mcp.pluginDownload}
          </Button>
        </div>
      </Section>

      <Section title={t.mcp.commonKicker}>
        <CodeField value={t.mcp.commonJson} multiline />
        <p className="mcp-connect-desc">{t.mcp.compatJsonDesc}</p>
      </Section>
    </PageFrame>

    {/* 工具一览表列宽超过阅读档 —— 以 page 档页框承载（组件 tier 组合表达，不写页面私有样式） */}
    <PageFrame tier="page" className="guide-page mcp-page">
      <Section title={t.mcp.toolsKicker} description={t.mcp.toolsIntro}>
        <div className="mcp-tools-table-wrapper">
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
        </div>
      </Section>
    </PageFrame>

    <PageFrame tier="reading" className="guide-page mcp-page">
      <Section title={t.mcp.agentsKicker}>
        <div className="guide-agent-stack">
          <AgentSteps title={t.mcp.qwenTitle} desc={t.mcp.qwenDesc} steps={t.mcp.qwenSteps} />
          <AgentSteps title={t.mcp.workbuddyTitle} desc={t.mcp.workbuddyDesc} steps={t.mcp.workbuddySteps} />
          <AgentSteps title={t.mcp.doubaoTitle} desc={t.mcp.doubaoDesc} steps={t.mcp.doubaoSteps} />
        </div>
      </Section>

      <Section title={t.mcp.trustKicker}>
        <ul className="guide-trust-list">
          <li>{t.mcp.trust1}</li>
          <li>{t.mcp.trust2}</li>
          <li>{t.mcp.trust3}</li>
          <li>{t.mcp.trust4}</li>
        </ul>
      </Section>
    </PageFrame>
  </>;
}
