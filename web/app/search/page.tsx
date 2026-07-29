import Link from "next/link";
import { ChemicalResult } from "@/components/ChemicalResult";
import { EntityId } from "@/components/EntityId";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ReactionResult } from "@/components/ReactionResult";
import { cookies } from "next/headers";
import { apiGet, ApiError, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";

type SearchParams = { q?: string; mode?: string; chemical_id?: string };

const CJK_RE = /[\u4e00-\u9fff\u3400-\u4dbf]/;

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const q = (params.q || "").trim();
  const mode = ["exact", "substructure", "similarity"].includes(params.mode || "") ? params.mode! : "exact";
  const chemicalId = /^\d+$/.test(params.chemical_id || "") ? Number(params.chemical_id) : null;
  const cjkBlocked = CJK_RE.test(q);
  const hasSession = (await cookies()).has("hgs_session");
  const authHeaders = hasSession ? { Cookie: (await cookies()).toString() } : undefined;
  let chemicals: Chemical[] = [];
  let reactions: ReactionLookup[] = [];
  let error = "";

  try {
    if (cjkBlocked) {
      // Skip the database entirely; the front-end search box already intercepts CJK input.
      // This guard exists for direct URL access and page refreshes.
    } else if (chemicalId && mode !== "exact") {
      if (!hasSession) {
        error = "结构检索（子结构 / 相似性）需要登录后使用。";
      } else {
        const related = await apiGet<{ chemicals: Chemical[] }>(`/chemicals/${chemicalId}/${mode}?limit=20`, 0, authHeaders);
        chemicals = related.chemicals;
      }
    } else if (q) {
      const data = await apiGet<SearchResponse>(`/search?q=${encodeURIComponent(q)}&mode=${mode}&page_size=20`);
      chemicals = data.chemicals;
      reactions = data.reactions || [];
    }
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 429) {
        error = "请求过于频繁，请稍后重试。";
      } else if (err.status === 503) {
        error = "查询超时，请使用更精确的名称、标识符或结构。";
      } else if (err.status === 422) {
        error = "查询条件不完整，请提供更多信息（如更完整的名称或更大的结构）。";
      } else if (err.status === 400) {
        error = "无法识别查询内容，请核对 SMILES 或标识符格式。";
      } else if (err.status === 404) {
        error = "查询对象不存在。";
      } else {
        error = "查询暂时不可用，请稍后重试。";
      }
    } else {
      error = "网络连接异常，请稍后重试。";
    }
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
      {cjkBlocked && (
        <div className="notice"><strong>暂不支持中文名称搜索</strong><p>请使用英文名称、CAS 号、SMILES 或 CID 进行查询。</p></div>
      )}
      {!error && !cjkBlocked && !q && !chemicalId && (
        <div className="search-guide">
          <section><strong>定位化合物</strong><p>名称、CAS、SMILES、PubChem CID、InChIKey、DTXSID、ChEMBL、ChEBI 等。</p></section>
          <section><strong>定位反应</strong><p>使用“reaction:编号”、ORD 记录号或 DOI。结构相关反应从化合物页进入。</p></section>
        </div>
      )}
      {chemicals.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>CHEMICALS</p><h2>{chemicalId ? relationLabel : "化合物"}</h2></div><span>显示 {chemicals.length} 条匹配记录</span></div>
          <div className="chemical-results">{chemicals.map((chemical) => <ChemicalResult chemical={chemical} key={chemical.id} />)}</div>
        </section>
      )}
      {reactions.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>REACTIONS</p><h2>反应记录</h2></div><span>显示 {reactions.length} 条匹配记录</span></div>
          <div className="reaction-results">{reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
        </section>
      )}
      {!error && !cjkBlocked && (q || chemicalId) && chemicals.length === 0 && reactions.length === 0 && (
        <div className="empty-state"><strong>没有匹配结果</strong><p>请核对查询内容或更换标识符。</p></div>
      )}
    </div>
  );
}
