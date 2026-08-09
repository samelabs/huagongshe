import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import { apiGet } from "@/lib/api";
import t from "@/lib/i18n";

type Stats = { chemicals: number; reactions: number; datasets: number; rdkit_failures: number };

export default async function Home() {
  let stats: Stats | null = null;
  try { stats = await apiGet<Stats>("/stats"); } catch {}
  return (
    <div className="home">
      <section className="hero">
        <h1>{t.home.hero}</h1>
        <GlobalSearch />
        <div className="search-examples" aria-label={t.home.searchExamples}>
          <span>{t.home.searchExampleLabel}</span>
          <Link href="/search?q=64-17-5">64-17-5</Link>
          <Link href="/search?q=CCO">CCO</Link>
          <Link href="/search?q=Aspirin">Aspirin</Link>
          <Link href="/search?q=cid%3A2244">CID 2244</Link>
        </div>
      </section>
      <section className="home-meta" aria-label={t.home.dataLabel}>
        <p className="home-meta-line">
          {stats ? t.home.dataLine(formatCount(stats.chemicals), formatCount(stats.reactions)) : "\u00A0"}
        </p>
      </section>
      <Link className="home-contribute" href="/guide">
        <span><span className="home-contribute-kicker">{t.home.ctaKicker}</span><strong>{t.home.ctaTitle}</strong></span>
        <span>{t.home.ctaBody}</span>
        <span className="home-contribute-link">{t.home.ctaLink}</span>
      </Link>
      <Link className="home-skills-entry" href="/skills">
        <span><span className="home-skills-kicker">OPEN SOURCE</span><strong>开放 Skills</strong></span>
        <span>158 个科学 AI Agent 技能，覆盖化学、生物、ML、科研写作等 12 个领域，来自 K-Dense-AI 开源项目</span>
        <span className="home-skills-link">浏览技能库 →</span>
      </Link>
    </div>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
