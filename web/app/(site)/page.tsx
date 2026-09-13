import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import t from "@/lib/i18n";

export default async function Home() {
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
          <Link className="button primary" href="/mcp-guide">{t.home.entryMcp}</Link>
          <Link className="button secondary" href="/api/agent-guide">{t.home.entryApi}</Link>
          <Link className="button secondary" href="/aichem">{t.home.entryWorkbench}</Link>
          <Link className="button secondary" href="/me/settings/api-tokens">{t.home.entryKey}</Link>
        </nav>
      </section>

      <p className="home-aux"><Link href="/skills">{t.home.skillsAux}</Link></p>
    </div>
  );
}
