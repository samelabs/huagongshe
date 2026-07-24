import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import { apiGet } from "@/lib/api";

type Stats = { chemicals: number; reactions: number; datasets: number; rdkit_failures: number };

export const revalidate = 3600;

export default async function Home() {
  let stats: Stats | null = null;
  try { stats = await apiGet<Stats>("/stats", 3600); } catch {}
  return (
    <div className="home">
      <section className="hero">
        <h1>查询开放化学数据</h1>
        <p className="hero-subtitle">查找化合物与反应，登录后保存自己的反应记录</p>
        <GlobalSearch />
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
        <div><span>个人反应记录</span><strong>保存并管理与你有关的反应</strong><p>登录后可以保存公开或仅自己可见的反应记录、收藏化学数据，也可以连接自己的 AI 助手整理资料。</p></div>
        <Link className="text-button" href="/guide">了解 AI 整理方法 →</Link>
      </section>
    </div>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
