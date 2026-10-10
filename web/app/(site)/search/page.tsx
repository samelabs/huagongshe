import Link from "next/link";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { EntityCard } from "@/components/EntityCard";
import { ReactionResult } from "@/components/ReactionResult";
import { SearchHero } from "@/components/SearchHero";
import { UrlTabs } from "@/components/UrlTabs";
import { Notice } from "@/components/ui/Notice";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphChem } from "@/components/ui/icons";
import { apiGet, ApiError, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";
import { localeAlternates } from "@/lib/alternates";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import type { Metadata } from "next";

type SearchParams = { q?: string; mode?: string; page?: string; focus?: string; type?: string };

/**
 * S2 (G1.5-A): 搜索页 metadata。
 * - 无参数入口 /search: 各语言独立 title/description/canonical/hreflang, 可索引。
 * - 带查询参数(q/mode/page)的内部结果页: noindex,follow —— 不为无限查询词
 *   生成 canonical/hreflang 集合, 也不进入 Sitemap。
 */
export async function generateMetadata({ searchParams }: { searchParams: Promise<SearchParams> }): Promise<Metadata> {
  const params = await searchParams;
  const hasQuery = Boolean(params.q || params.mode || params.page || params.focus);
  if (hasQuery) {
    return { robots: { index: false, follow: true } };
  }
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return {
    title: t.search.title,
    description: t.search.seoDesc,
    alternates: localeAlternates("/search", locale),
  };
}

const PAGE_SIZE = 30;
/** URL 模式 ⊃ API 模式：structure（精确结构）无独立 API mode，请求时映射回 exact。
 *  urlMode 保留 structure 用于 Segmented 回显/结果分类链接；mode 是 API 请求
 *  模式变量（tests/test_structure_search_final.py 钉住 `/search?q=…&mode=${mode}`
 *  与翻页模板，变量名不可改）。 */
type UrlMode = "exact" | "structure" | "substructure" | "similarity";
const URL_MODES: UrlMode[] = ["exact", "structure", "substructure", "similarity"];

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  const q = (params.q || "").trim();
  const urlMode: UrlMode = URL_MODES.includes(params.mode as UrlMode) ? (params.mode as UrlMode) : "exact";
  const mode = urlMode === "structure" ? "exact" : urlMode;
  const page = Math.max(1, Math.min(20, Number.parseInt(params.page || "1", 10) || 1));
  let chemicals: Chemical[] = [];
  let reactions: ReactionLookup[] = [];
  let total: number | null = null;
  let hasMore = false;
  let error = "";
  let fetchPending = false;
  let similarityThreshold: number | null = null;
  let capped = false;
  let redirectTarget: string | null = null;
  // 结构检索登录墙: mode!=exact 需要会话, SSR 转发浏览器 cookie 供 API 鉴权
  // P0(0902): exact 也透传 — 登录用户 CB miss 入列拿 80 分(此前 exact 匿名 50 分)
  const cookieValue = (await headers()).get("cookie") || "";
  const sessionHeaders = cookieValue
    ? { cookie: cookieValue }
    : undefined;
  const authed = (await cookies()).has("hgs_session");

  try {
    if (q) {
      const data = await apiGet<SearchResponse>(
        `/search?q=${encodeURIComponent(q)}&mode=${mode}&threshold=0.7&page=${page}&page_size=${PAGE_SIZE}`, sessionHeaders
      );
      if (urlMode === "similarity" && typeof data.threshold === "number") {
        similarityThreshold = data.threshold;
      }
      chemicals = data.chemicals;
      reactions = data.reactions || [];
      total = data.total ?? null;
      // Search System Governance: 翻页入口只消费 API 的权威 has_more,
      // 不再用 total===null && len===PAGE_SIZE 猜测。
      hasMore = data.has_more === true;
      // capped(0915): substructure snapshot 达到产品上限 — 展示层禁把 total
      // 冒充数据库真实总数, 文案切 capped 语义。
      capped = data.capped === true;
      fetchPending = data.cas_fetch_pending === true;
      // 0902 P3b: 库外 CAS 同步拉命中 — 数据已落库, 服务端直达详情页(零轮询)
      // redirect() 以抛 NEXT_REDIRECT 异常实现, 必须在 try 外执行,
      // 否则被下方 catch 吞成 networkError(0902 实测翻车: 列表+错误横幅同屏)。
      if (data.cas_fetch_chemical_id && page === 1) {
        redirectTarget = withLocale(`/chemical/${data.cas_fetch_chemical_id}`, locale);
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

  /* 化合物卡片收藏初始态（登录时取已收藏 id 集；失败按未收藏，乐观更新兜底）。
     命名注意：本文件源码被 tests/test_structure_search_final.py 逐串钉住，
     变量/标识符不得含被禁子串。 */
  let favoredSet = new Set<number>();
  if (authed) {
    try {
      const followed = await apiGet<{ items: { id: number }[] }>("/users/me/follows/chemicals?page=1&page_size=100", sessionHeaders);
      favoredSet = new Set(followed.items.map((item) => item.id));
    } catch { /* 保持空集 */ }
  }

  const relationLabel = urlMode === "substructure" ? t.search.substructure : urlMode === "similarity" ? t.search.similarity : urlMode === "structure" ? t.search.modeExactStructure : null;
  const start = (page - 1) * PAGE_SIZE + 1;
  const shown = start + chemicals.length - 1;
  // 结果分类链接（Tabs 切换）：保留 URL 模式（含 structure 回显）
  const typeHref = (nextType?: string) =>
    withLocale(`/search?q=${encodeURIComponent(q)}${urlMode !== "exact" ? `&mode=${urlMode}` : ""}${nextType === "reactions" ? "&type=reactions" : ""}${page > 1 ? `&page=${page}` : ""}`, locale);
  // 结果分类（Step 10 §9.3）：只显示当前搜索接口实际返回的类型 ——
  // reactions 仅在 exact 首页由接口返回；只有化合物时不显示 Tabs，计数直接放标题行。
  const hasReactions = reactions.length > 0;
  const activeType = params.type === "reactions" && hasReactions ? "reactions" : "chemicals";

  if (redirectTarget) redirect(redirectTarget);  // try 外: NEXT_REDIRECT 异常直穿
  return (
    <div className="content-page search-page">
      <header className="search-head">
        <h1>{relationLabel ? `${relationLabel}${t.search.resultSuffix}` : t.search.title}</h1>
        <SearchHero initial={q} initialMode={urlMode} authed={authed} autoFocus={params.focus === "1"} contextLabel={t.search.title} />
        {relationLabel && q && (
          <p className="context-line">
            {t.search.queryStructurePrefix}<code>{q}</code>{t.search.queryStructure}{relationLabel}{urlMode === "similarity" && similarityThreshold !== null ? t.search.similarityThreshold(similarityThreshold) : ""}{capped ? t.search.cappedHint : ""}
          </p>
        )}
      </header>
      {error && <div className="notice error" role="alert">{error}</div>}
      {chemicals.length > 0 && (
        <section className="results-section">
          {hasReactions ? (
            <UrlTabs
              ariaLabel={t.search.resultTabsLabel}
              value={activeType}
              tabs={[
                { id: "chemicals", label: t.search.chemicalResults, count: total != null ? total : chemicals.length },
                { id: "reactions", label: t.search.reactionResults, count: reactions.length },
              ]}
              hrefFor={(id) => typeHref(id === "reactions" ? "reactions" : undefined)}
            />
          ) : (
            <div className="section-heading">
              <div><h2>{relationLabel ?? t.search.chemicalResults}</h2></div>
              <span>
                {capped
                  ? t.search.showingCappedRange(start, shown)
                  : total !== null
                    ? t.search.showingRange(start, shown, total)
                    : t.search.showingResults(chemicals.length)}
              </span>
            </div>
          )}
          {activeType === "chemicals" && (
            <>
              <div className="entity-card-grid">{chemicals.map((chemical) => <EntityCard chemical={chemical} key={chemical.id} favored={favoredSet.has(chemical.id)} />)}</div>
              {hasMore && (
                <div className="load-more">
                  {/* 翻页链接保留 q 与 mode（tests/test_structure_search_final.py 钉住模板） */}
                  <Link className="hg-btn secondary" href={withLocale(`/search?q=${encodeURIComponent(q)}${mode !== "exact" ? `&mode=${mode}` : ""}&page=${page + 1}`, locale)}>
                    {t.search.loadMore}
                  </Link>
                </div>
              )}
            </>
          )}
          {activeType === "reactions" && (
            <div className="reaction-results">{reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
          )}
        </section>
      )}
      {!error && q && chemicals.length === 0 && reactions.length === 0 && (
        <div className="search-empty">
          {fetchPending && <Notice tone="info">{t.search.fetchPendingHint.replace("{cas}", q)}</Notice>}
          <EmptyState icon={<GlyphChem />} title={t.search.noResultsFor(q)}>
            {t.search.noResultsTryHint}
          </EmptyState>
          <Link className="hg-btn secondary" href={withLocale("/search", locale)}>{t.search.clearQuery}</Link>
        </div>
      )}
    </div>
  );
}
