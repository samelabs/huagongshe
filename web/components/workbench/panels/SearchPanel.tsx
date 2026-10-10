"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiGet, molSvgUrl, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { IconSearch } from "@/components/ui/icons";
import { Input } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Segmented } from "@/components/ui/Segmented";
import { Skeleton } from "@/components/ui/Skeleton";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { resolveChemicalName } from "@/lib/chemicalName";
import { PanelHeading, panelErrorMessage } from "../shared";
import type { LoadState } from "../types";

type SearchMode = "exact" | "substructure" | "similarity";

/**
 * 工作台查询面板（Step 9 Part B.6：组件换 ui 库 —— Input/Button/Segmented/
 * Skeleton/Notice/EmptyState；计算与业务逻辑不变）。
 * 搜索框 + 模式切换（精确/子结构/相似）+ 结果区
 */
export function SearchPanel({ initialQuery }: { initialQuery?: string }) {
  const t = useDictionary();
  const locale = useLocale();
  const [query, setQuery] = useState(initialQuery ?? "");
  const [mode, setMode] = useState<SearchMode>("exact");
  const [chemicals, setChemicals] = useState<Chemical[]>([]);
  const [reactions, setReactions] = useState<ReactionLookup[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [state, setState] = useState<LoadState>(initialQuery ? "loading" : "idle");
  const [submitted, setSubmitted] = useState(!!initialQuery);
  const [error, setError] = useState<unknown>(null);
  const latestRequest = useRef(0);

  function doSearch(q: string, m: SearchMode) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setSubmitted(true);
    setState("loading");
    setError(null);
    // Drop stale responses: only the newest request may commit results.
    const requestId = ++latestRequest.current;
    apiGet<SearchResponse>(`/search?q=${encodeURIComponent(trimmed)}&mode=${m}&page=1&page_size=30`)
      .then((data) => {
        if (requestId !== latestRequest.current) return;
        setChemicals(data.chemicals);
        setReactions(data.reactions || []);
        setTotal(data.total ?? null);
        // Search System Governance: 继续入口只认 API 权威 has_more
        setHasMore(data.has_more === true);
        setState("ready");
      })
      .catch((err: unknown) => {
        if (requestId !== latestRequest.current) return;
        setError(err); setState("error");
      });
  }

  // 从首页带查询词跳转时自动搜索
  useEffect(() => {
    if (initialQuery) doSearch(initialQuery, "exact");
  }, []);

  const hasResults = chemicals.length > 0 || reactions.length > 0;

  return (
    <section className="wb-panel wb-search">
      <PanelHeading title={t.me.tabSearch} subtitle={t.me.searchHint} />

      {/* 搜索框 — 工作台自有布局，控件用 ui 库（Step 9） */}
      <form className="wb-search-form" onSubmit={(e) => { e.preventDefault(); doSearch(query, mode); }}>
        <div className="wb-search-field">
          <Input
            type="text"
            enterKeyHint="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="CAS, Name, SMILES, InChIKey"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            aria-label={t.me.searchButton}
          />
          <Button type="submit" variant="primary">{t.me.searchButton}</Button>
        </div>
        {/* 模式切换（§6：检索方式用 Segmented） */}
        <Segmented
          ariaLabel={t.me.searchHint}
          options={[
            { value: "exact" as const, label: t.me.searchModeExact },
            { value: "substructure" as const, label: t.me.searchModeSubstructure },
            { value: "similarity" as const, label: t.me.searchModeSimilarity },
          ]}
          value={mode}
          onChange={(value) => setMode(value)}
        />
      </form>

      {/* 结果区 */}
      {!submitted && <EmptyState icon={<IconSearch />} title={t.me.searchNoQuery} />}
      {submitted && state === "loading" && (
        <div className="wb-skeleton-list" aria-hidden="true">
          {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} variant="card" />)}
        </div>
      )}
      {submitted && state === "error" && (
        <Notice tone="err">{panelErrorMessage(error, t)}</Notice>
      )}
      {submitted && state === "ready" && !hasResults && (
        <EmptyState icon={<IconSearch />} title={t.me.searchNoResults} />
      )}

      {submitted && state === "ready" && chemicals.length > 0 && (
        <div className="wb-search-section">
          <h3>{t.me.searchResultCompound}{total != null && ` (${total})`}</h3>
          <div className="wb-search-chemicals">
            {chemicals.map((chem) => (
              <Link key={chem.id} className="wb-search-chemical" href={withLocale(`/chemical/${chem.id}`, locale)}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img loading="lazy" src={molSvgUrl(chem.id, 160, 110)} alt="" />
                <div>
                  <strong>{resolveChemicalName(chem, t.common.hcidLabel, locale).title}</strong>
                  <EntityBadge kind="chemical" id={chem.id} size="xs" ariaLabel={t.common.hcidLabel(chem.id)} />
                  <span>{chem.molecular_formula || chem.inchikey || ""}</span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {submitted && state === "ready" && reactions.length > 0 && (
        <div className="wb-search-section">
          <h3>{t.me.searchResultReaction}</h3>
          <div className="wb-search-reactions">
            {reactions.map((rxn) => (
              <Link key={rxn.id} className="wb-search-reaction" href={withLocale(`/reaction/${rxn.id}`, locale)}>
                <EntityBadge kind="reaction" id={rxn.id} size="xs" ariaLabel={t.common.hridLabel(rxn.id)} />
                <small>{rxn.doi || rxn.ord_id || rxn.dataset_name || ""}</small>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* 更多结果跳主站搜索页: 只认 API has_more(名称搜索 total 恒 null) */}
      {submitted && state === "ready" && hasMore && (
        <Link className="wb-home-more-search" href={withLocale(`/search?q=${encodeURIComponent(query)}&mode=${mode}`, locale)}>
          {t.me.homeViewAll}{total != null ? ` (${total})` : ""}
        </Link>
      )}
    </section>
  );
}
