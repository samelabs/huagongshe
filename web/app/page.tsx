import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import { apiGet } from "@/lib/api";

type Stats = { chemicals: number; reactions: number; datasets: number; rdkit_failures: number };

export const dynamic = "force-dynamic";

export default async function Home() {
  let stats: Stats | null = null;
  try { stats = await apiGet<Stats>("/stats", 3600); } catch {}
  return (
    <div className="home">
      <section className="hero">
        <h1>从一个化合物开始</h1>
        <GlobalSearch autoFocus />
        <div className="search-examples" aria-label="查询示例">
          <span>试试</span>
          <Link href="/search?q=64-17-5">64-17-5</Link>
          <Link href="/search?q=CCO">CCO</Link>
          <Link href="/search?q=Aspirin">Aspirin</Link>
          <Link href="/search?q=cid%3A2244">CID 2244</Link>
        </div>
      </section>
      <section className="home-meta" aria-label="数据概况">
        {stats && (
          <div className="home-stats">
            <div className="home-stat">
              <strong>{formatCount(stats.chemicals)}</strong>
              <span>化合物</span>
            </div>
            <div className="home-stat">
              <strong>{formatCount(stats.reactions)}</strong>
              <span>反应</span>
            </div>
          </div>
        )}
      </section>
      <section className="home-contribute">
        <div><strong>建立自己的反应仓库</strong><p>从网页表单发布，或让 AI 从文献和实验文档中整理。你可以持续编辑、调整公开范围或删除自己的反应。</p></div>
        <div><Link className="button primary small" href="/submit">发布反应</Link><Link className="text-button" href="/guide">AI 提交指南</Link></div>
      </section>
    </div>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
