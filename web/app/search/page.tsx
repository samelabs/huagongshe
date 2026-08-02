import Link from "next/link";
import { ChemicalResult } from "@/components/ChemicalResult";
import { EntityId } from "@/components/EntityId";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ReactionResult } from "@/components/ReactionResult";
import { cookies } from "next/headers";
import { apiGet, ApiError, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";
import t from "@/lib/i18n";

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
        error = t.search.substructureLogin;
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
        error = t.search.errRateLimit;
      } else if (err.status === 503) {
        error = t.search.errTimeout;
      } else if (err.status === 422) {
        error = t.search.errIncomplete;
      } else if (err.status === 400) {
        error = t.search.errUnrecognized;
      } else if (err.status === 404) {
        error = t.search.errNotFound;
      } else {
        error = t.search.errGeneric;
      }
    } else {
      error = t.common.networkError;
    }
  }

  const relationLabel = mode === "substructure" ? t.search.substructure : t.search.similarity;
  return (
    <div className="content-page search-page">
      <header className="search-head">
        <p className="page-kicker">DATA FINDER</p>
        <h1>{chemicalId ? `${relationLabel}${t.search.resultSuffix}` : t.search.title}</h1>
        <GlobalSearch initial={q} compact />
        {chemicalId && <p className="context-line">{t.search.basedOnStructure}<Link href={`/chemical/${chemicalId}`}><EntityId kind="chemical" id={chemicalId} compact /></Link>{t.search.queryStructure}{relationLabel}{mode === "similarity" ? t.search.similarityThreshold : ""}</p>}
      </header>
      {error && <div className="notice error">{error}</div>}
      {cjkBlocked && (
        <div className="notice"><strong>{t.search.cjkNotice}</strong><p>{t.search.cjkHint}</p></div>
      )}
      {!error && !cjkBlocked && !q && !chemicalId && (
        <div className="search-guide">
          <section><strong>{t.search.locateChemical}</strong><p>{t.search.hintName}</p></section>
          <section><strong>{t.search.locateReaction}</strong><p>{t.search.hintReaction}</p></section>
        </div>
      )}
      {chemicals.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>CHEMICALS</p><h2>{chemicalId ? relationLabel : t.search.chemicalResults}</h2></div><span>{t.search.showingResults(chemicals.length)}</span></div>
          <div className="chemical-results">{chemicals.map((chemical) => <ChemicalResult chemical={chemical} key={chemical.id} />)}</div>
        </section>
      )}
      {reactions.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>REACTIONS</p><h2>{t.search.reactionResults}</h2></div><span>{t.search.showingResults(reactions.length)}</span></div>
          <div className="reaction-results">{reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
        </section>
      )}
      {!error && !cjkBlocked && (q || chemicalId) && chemicals.length === 0 && reactions.length === 0 && (
        <div className="empty-state"><strong>{t.search.noResults}</strong><p>{t.search.noResultsHint}</p></div>
      )}
    </div>
  );
}
