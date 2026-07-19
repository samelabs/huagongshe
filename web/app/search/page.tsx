import Link from "next/link";
import { SearchBox } from "@/components/SearchBox";
import { Molecule } from "@/components/Molecule";
import { apiGet, type Chemical, type SearchResponse } from "@/lib/api";

type SearchParams = { q?: string; mode?: string; chemical_id?: string };

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const q = (params.q || "").trim();
  const mode = ["exact", "substructure", "similarity"].includes(params.mode || "") ? params.mode! : "exact";
  const chemicalId = /^\d+$/.test(params.chemical_id || "") ? Number(params.chemical_id) : null;
  let chemicals: Chemical[] = [];
  let error = "";

  try {
    if (chemicalId && mode !== "exact") {
      const related = await apiGet<{ chemicals: Chemical[] }>(`/chemicals/${chemicalId}/${mode}?limit=20`);
      chemicals = related.chemicals;
    } else if (q) {
      const data = await apiGet<SearchResponse>(`/search?q=${encodeURIComponent(q)}&mode=${mode}&page_size=20`);
      chemicals = data.chemicals;
    }
  } catch {
    error = "查询暂时不可用，请稍后重试或缩小结构范围。";
  }

  const relationLabel = mode === "substructure" ? "子结构" : "相似结构";
  return (
    <div className="page">
      <div className="top-search"><SearchBox initial={q} initialMode={mode} /></div>
      {chemicalId && mode !== "exact" && <h2 className="section-label">化合物 #{chemicalId} 的{relationLabel}</h2>}
      {error && <div className="error">{error}</div>}
      {chemicals.length > 0 && (
        <div className="result-list">
          {chemicals.map((chemical) => (
            <Link className="result-row" href={`/chemical/${chemical.id}`} key={chemical.id}>
              <div className="mol-frame"><Molecule smiles={chemical.smiles} width={110} height={80} /></div>
              <div>
                <p className="result-title">{chemical.preferred_name || chemical.iupac_name || `化合物 #${chemical.id}`}</p>
                <p className="result-sub">{chemical.cas_numbers[0] ? `CAS ${chemical.cas_numbers[0]} · ` : ""}{chemical.molecular_formula || ""}</p>
                {chemical.smiles && <p className="result-sub mono">{chemical.smiles}</p>}
              </div>
              <span className="result-arrow">→</span>
            </Link>
          ))}
        </div>
      )}
      {!error && (q || chemicalId) && chemicals.length === 0 && <div className="empty">没有找到匹配的化合物</div>}
    </div>
  );
}
