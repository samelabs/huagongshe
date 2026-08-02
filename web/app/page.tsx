import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import { apiGet } from "@/lib/api";
import t from "@/lib/i18n";

type Stats = { chemicals: number; reactions: number; datasets: number; rdkit_failures: number };

export const revalidate = 3600;

export default async function Home() {
  let stats: Stats | null = null;
  try { stats = await apiGet<Stats>("/stats", 3600); } catch {}
  return (
    <div className="home">
      <section className="hero">
        <h1>{t.home.hero}</h1>
        <p className="hero-subtitle">{t.home.subtitle}</p>
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
        {stats && (
          <p className="home-meta-line">{t.home.dataLine(formatCount(stats.chemicals), formatCount(stats.reactions))}</p>
        )}
      </section>
      <section className="home-contribute">
        <div><span>{t.home.ctaKicker}</span><strong>{t.home.ctaTitle}</strong><p>{t.home.ctaBody}</p></div>
        <Link className="text-button" href="/guide">{t.home.ctaLink}</Link>
      </section>
    </div>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
