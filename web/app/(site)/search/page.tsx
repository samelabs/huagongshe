import Link from "next/link";
import { ChemicalResult } from "@/components/ChemicalResult";
import { EntityId } from "@/components/shared/EntityId";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ReactionResult } from "@/components/ReactionResult";
import { cookies } from "next/headers";
import { apiGet, ApiError, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";
import t from "@/lib/i18n";

type SearchParams = { q?: string; mode?: string; chemical_id?: string; page?: string };

const CJK_RE = /[\u4e00-\u9fff\u3400-\u4dbf]/;
const PAGE_SIZE = 30;

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const q = (params.q || "").trim();
  const mode = ["exact", "substructure", "similarity"].includes(params.mode || "") ? params.mode! : "exact";
  const chemicalId = /^\d+$/.test(params.chemical_id || "") ? Number(params.chemical_id) : null;
  const page = Math.max(1, Math.min(20, Number.parseInt(params.page || "1", 10) || 1));
  const cjkBlocked = CJK_RE.test(q);
  const hasSession = (await cookies()).has("hgs_session");
  const authHeaders = hasSession ? { Cookie: (await cookies()).toString() } : undefined;
  let chemicals: Chemical[] = [];
  let reactions: ReactionLookup[] = [];
  let total: number | null = null;
  let error = "";

  try {
    if (cjkBlocked) {
      // Skip the database entirely; the front-end search box already intercepts CJK input.
      // This guard exists for direct URL access and page refreshes.
    } else if (chemicalId && mode !== "exact") {
      if (!hasSession) {
        error = t.search.substructureLogin;
      } else {
        const related = await apiGet<{ chemicals: Chemical[]; total: number | null }>(
          `/chemicals/${chemicalId}/${mode}?page=${page}&page_size=${PAGE_SIZE}`, authHeaders
        );
        chemicals = related.chemicals;
        total = related.total ?? null;
      }
    } else if (q) {
      const data = await apiGet<SearchResponse>(
        `/search?q=${encodeURIComponent(q)}&mode=${mode}&page=${page}&page_size=${PAGE_SIZE}`
      );
      chemicals = data.chemicals;
      reactions = data.reactions || [];
      total = data.total ?? null;
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
  const hasMore = total === null ? chemicals.length === PAGE_SIZE : page * PAGE_SIZE < total;
  const start = (page - 1) * PAGE_SIZE + 1;
  const shown = start + chemicals.length - 1;

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
          <section>
            <span className="search-guide-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><path d="M12 3l7.8 4.5v9L12 21l-7.8-4.5v-9L12 3z" /><path d="M12 9l4 2.3v4.4L12 18l-4-2.3v-4.4L12 9z" /></svg></span>
            <strong>{t.search.locateChemical}</strong>
            <p>{t.search.hintName}</p>
          </section>
          <section>
            <span className="search-guide-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12h14" /><path d="M13 6l6 6-6 6" /></svg></span>
            <strong>{t.search.locateReaction}</strong>
            <p>{t.search.hintReaction}</p>
          </section>
        </div>
      )}
      {chemicals.length > 0 && (
        <section className="results-section">
          <div className="section-heading">
            <div><p>CHEMICALS</p><h2>{chemicalId ? relationLabel : t.search.chemicalResults}</h2></div>
            <span>{total !== null ? t.search.showingRange(start, shown, total) : t.search.showingResults(chemicals.length)}</span>
          </div>
          <div className="chemical-results">{chemicals.map((chemical) => <ChemicalResult chemical={chemical} key={chemical.id} />)}</div>
          {hasMore && (
            <div className="load-more">
              <Link className="load-more-btn" href={`/search?${chemicalId ? `chemical_id=${chemicalId}&mode=${mode}` : `q=${encodeURIComponent(q)}`}&page=${page + 1}`}>
                {t.search.loadMore}
              </Link>
            </div>
          )}
        </section>
      )}
      {reactions.length > 0 && (
        <section className="results-section">
          <div className="section-heading"><div><p>REACTIONS</p><h2>{t.search.reactionResults}</h2></div><span>{t.search.showingResults(reactions.length)}</span></div>
          <div className="reaction-results">{reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
        </section>
      )}
      {!error && !cjkBlocked && (q || chemicalId) && chemicals.length === 0 && reactions.length === 0 && (
        <div className="empty-state empty-state--search">
          <span className="empty-state-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></svg></span>
          <strong>{t.search.noResults}</strong>
          <p>{t.search.noResultsHint}</p>
          <Link className="button secondary" href="/search">{t.search.clearQuery}</Link>
        </div>
      )}
    </div>
  );
}
