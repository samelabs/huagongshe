import Link from "next/link";
import { ChemicalResult } from "@/components/ChemicalResult";
import { EntityId } from "@/components/EntityId";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ReactionResult } from "@/components/ReactionResult";
import { apiGet, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";

type SearchParams = { q?: string; mode?: string; chemical_id?: string };

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const q = (params.q || "").trim();
  const mode = ["exact", "substructure", "similarity"].includes(params.mode || "") ? params.mode! : "exact";
  const chemicalId = /^\d+$/.test(params.chemical_id || "") ? Number(params.chemical_id) : null;
  let chemicals: Chemical[] = [];
  let reactions: ReactionLookup[] = [];
  let error = "";

  try {
    if (chemicalId && mode !== "exact") {
      const related = await apiGet<{ chemicals: Chemical[] }>(`/chemicals/${chemicalId}/${mode}?limit=20`);
      chemicals = related.chemicals;
    } else if (q) {
      const data = await apiGet<SearchResponse>(`/search?q=${encodeURIComponent(q)}&mode=${mode}&page_size=20`);
      chemicals = data.chemicals;
      reactions = data.reactions || [];
    }
  } catch {
    error = "查询暂时不可用。请稍后重试，或缩小结构检索范围。";
  }

  const relationLabel = mode === "substructure" ? "子结构匹配" : "相似结构";
  return (
    <div className="content-page search-page">
      <header className="search-head">
        <p className="page-kicker">DATA FINDER</p>
        <h1>{chemicalId ? `${relationLabel}结果` : "查询化学数据"}</h1>
        <GlobalSearch initial={q} compact />
        {chemicalId && <p className="context-line">以 <Link href={`/chemical/${chemicalId}`}><EntityId kind="chemical" id={chemicalId} compact /></Link> 为查询结构的{relationLabel}{mode === "similarity" ? "（相似度 ≥ 70%）" : ""}</p>}
      </header>
      {error && <div className="notice error">{error}</div>}
      {!error && !q && !chemicalId && (
        <div className="search-guide">
          <section><strong>定位化合物</strong><p>名称、CAS、SMILES、PubChem CID、InChIKey、DTXSID、ChEMBL、ChEBI 等。</p></section>
          <section><strong>定位反应</strong><p>使用“reaction:编号”、ORD 记录号或 DOI。结构相关反应从化合物页进入。</p></section>
        </div>
      )}
      {chemicals.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>CHEMICALS</p><h2>{chemicalId ? relationLabel : "化合物"}</h2></div><span>{chemicals.length} 个结果</span></div>
          <div className="chemical-results">{chemicals.map((chemical) => <ChemicalResult chemical={chemical} key={chemical.id} />)}</div>
        </section>
      )}
      {reactions.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>REACTIONS</p><h2>反应记录</h2></div><span>{reactions.length} 个结果</span></div>
          <div className="reaction-results">{reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
        </section>
      )}
      {!error && (q || chemicalId) && chemicals.length === 0 && reactions.length === 0 && (
        <div className="empty-state"><strong>没有匹配结果</strong><p>请核对查询内容或更换标识符。</p></div>
      )}
    </div>
  );
}
