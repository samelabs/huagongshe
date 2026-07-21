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
        <div><span>AI-ASSISTED</span><strong>让 AI 参与反应数据维护</strong><p>把网页、文献、专利或实验文档交给 AI。AI 使用你的 API Token 查询、校验并提交结构化反应；你在个人仓库继续编辑、调整公开范围或删除。</p></div>
        <Link className="text-button" href="/guide">查看 AI 使用指南 →</Link>
      </section>
    </div>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
