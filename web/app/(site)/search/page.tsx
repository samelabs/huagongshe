import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { ChemicalResult } from "@/components/ChemicalResult";
import { EntityId } from "@/components/shared/EntityId";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ReactionResult } from "@/components/ReactionResult";
import { apiGet, ApiError, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";
import t from "@/lib/i18n";

type SearchParams = { q?: string; mode?: string; chemical_id?: string; page?: string };

const PAGE_SIZE = 30;

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const q = (params.q || "").trim();
  const mode = ["exact", "substructure", "similarity"].includes(params.mode || "") ? params.mode! : "exact";
  const chemicalId = /^\d+$/.test(params.chemical_id || "") ? Number(params.chemical_id) : null;
  const page = Math.max(1, Math.min(20, Number.parseInt(params.page || "1", 10) || 1));
  let chemicals: Chemical[] = [];
  let reactions: ReactionLookup[] = [];
  let total: number | null = null;
  let error = "";
  let fetchPending = false;
  let redirectTarget: string | null = null;
  // 结构检索登录墙: mode!=exact 需要会话, SSR 转发浏览器 cookie 供 API 鉴权
  // P0(0902): exact 也透传 — 登录用户 CB miss 入列拿 80 分(此前 exact 匿名 50 分)
  const cookieValue = (await headers()).get("cookie") || "";
  const sessionHeaders = cookieValue
    ? { cookie: cookieValue }
    : undefined;

  try {
    if (chemicalId && mode !== "exact") {
      const related = await apiGet<{ chemicals: Chemical[]; total: number | null }>(
        `/chemicals/${chemicalId}/${mode}?page=${page}&page_size=${PAGE_SIZE}`, sessionHeaders
      );
      chemicals = related.chemicals;
      total = related.total ?? null;
    } else if (q) {
      const data = await apiGet<SearchResponse>(
        `/search?q=${encodeURIComponent(q)}&mode=${mode}&page=${page}&page_size=${PAGE_SIZE}`, sessionHeaders
      );
      chemicals = data.chemicals;
      reactions = data.reactions || [];
      total = data.total ?? null;
      fetchPending = data.cas_fetch_pending === true;
      // 0902 P3b: 库外 CAS 同步拉命中 — 数据已落库, 服务端直达详情页(零轮询)
      // redirect() 以抛 NEXT_REDIRECT 异常实现, 必须在 try 外执行,
      // 否则被下方 catch 吞成 networkError(0902 实测翻车: 列表+错误横幅同屏)。
      if (data.cas_fetch_chemical_id && page === 1) {
        redirectTarget = `/chemical/${data.cas_fetch_chemical_id}`;
      }
    }
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 429) {
        error = t.search.errRateLimit;
      } else if (err.status === 401) {
        error = t.search.errLoginRequired;
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

  if (redirectTarget) redirect(redirectTarget);  // try 外: NEXT_REDIRECT 异常直穿
  return (
    <div className="content-page search-page">
      <header className="search-head">
        <p className="page-kicker">DATA FINDER</p>
        <h1>{chemicalId ? `${relationLabel}${t.search.resultSuffix}` : t.search.title}</h1>
        <GlobalSearch initial={q} compact />
        {chemicalId && <p className="context-line">{t.search.basedOnStructure}<Link href={`/chemical/${chemicalId}`}><EntityId kind="chemical" id={chemicalId} compact /></Link>{t.search.queryStructure}{relationLabel}{mode === "similarity" ? t.search.similarityThreshold : ""}</p>}
      </header>
      {error && <div className="notice error">{error}</div>}
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
      {!error && (q || chemicalId) && chemicals.length === 0 && reactions.length === 0 && (
        <div className="empty-state empty-state--search">
          <span className="empty-state-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></svg></span>
          {fetchPending ? (
            <>
              <strong>{t.search.fetchPendingTitle}</strong>
              <p>{t.search.fetchPendingHint.replace("{cas}", q)}</p>
            </>
          ) : (
            <>
              <strong>{t.search.noResults}</strong>
              <p>{t.search.noResultsHint}</p>
            </>
          )}
          <Link className="button secondary" href="/search">{t.search.clearQuery}</Link>
        </div>
      )}
    </div>
  );
}
