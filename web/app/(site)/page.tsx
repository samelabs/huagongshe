import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

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
