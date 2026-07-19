import { SearchBox } from "@/components/SearchBox";
import { apiGet } from "@/lib/api";

type Stats = { chemicals: number; reactions: number; datasets: number; rdkit_failures: number };

export const dynamic = "force-dynamic";

export default async function Home() {
  let stats: Stats | null = null;
  try { stats = await apiGet<Stats>("/stats", 3600); } catch {}
  return (
    <div className="home">
      <section className="hero">
        <h1>化合物与反应查询</h1>
        <p className="lead">输入名称、CAS、SMILES 或外部编号查询化合物。</p>
        <SearchBox autoFocus />
        <p className="search-hint">例如：64-17-5　CCO　Aspirin　DTXSID7020182</p>
      </section>
      <section className="home-meta" aria-label="数据概况">
        {stats && (
          <div className="home-stats">
            <div className="home-stat">
              <strong>{formatCount(stats.chemicals)}</strong>
              <span>个化合物</span>
            </div>
            <div className="home-stat">
              <strong>{formatCount(stats.reactions)}</strong>
              <span>条反应</span>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
