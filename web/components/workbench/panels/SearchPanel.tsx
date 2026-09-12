"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiGet, molSvgUrl, type Chemical, type ReactionLookup, type SearchResponse } from "@/lib/api";
import { EntityId } from "@/components/shared/EntityId";
import t from "@/lib/i18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { PanelHeading, WbEmpty, PanelLoading, PanelError } from "../shared";
import type { LoadState } from "../types";

type SearchMode = "exact" | "substructure" | "similarity";

/**
 * 工作台查询面板
 * 搜索框 + 模式切换（精确/子结构/相似）+ 结果区
 */
export function SearchPanel({ initialQuery }: { initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery ?? "");
  const [mode, setMode] = useState<SearchMode>("exact");
  const [chemicals, setChemicals] = useState<Chemical[]>([]);
  const [reactions, setReactions] = useState<ReactionLookup[]>([]);
  const [total, setTotal] = useState<number | null>(null);
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

      {/* 搜索框 — 工作台自有样式，不引用主站 class */}
      <form className="wb-search-form" onSubmit={(e) => { e.preventDefault(); doSearch(query, mode); }}>
        <div className="wb-search-field">
          <svg className="wb-search-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.5" y2="16.5" />
          </svg>
          <input
            type="text"
            enterKeyHint="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.me.searchPlaceholder}
            autoFocus
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" className="wb-search-submit">{t.me.searchButton}</button>
        </div>
        {/* 模式切换 */}
        <div className="wb-search-modes">
          <button type="button" className={mode === "exact" ? "active" : ""} onClick={() => setMode("exact")}>{t.me.searchModeExact}</button>
          <button type="button" className={mode === "substructure" ? "active" : ""} onClick={() => setMode("substructure")}>{t.me.searchModeSubstructure}</button>
          <button type="button" className={mode === "similarity" ? "active" : ""} onClick={() => setMode("similarity")}>{t.me.searchModeSimilarity}</button>
        </div>
      </form>

      {/* 结果区 */}
      {!submitted && <div className="wb-search-idle">{t.me.searchNoQuery}</div>}
      {submitted && state === "loading" && <PanelLoading variant="grid" rows={3} />}
      {submitted && state === "error" && <PanelError error={error} />}
      {submitted && state === "ready" && !hasResults && <WbEmpty text={t.me.searchNoResults} />}

      {submitted && state === "ready" && chemicals.length > 0 && (
        <div className="wb-search-section">
          <h3>{t.me.searchResultCompound}{total != null && ` (${total})`}</h3>
          <div className="wb-search-chemicals">
            {chemicals.map((chem) => (
              <Link key={chem.id} className="wb-search-chemical" href={`/chemical/${chem.id}`}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img loading="lazy" src={molSvgUrl(chem.id, 160, 110)} alt="" />
                <div>
                  <strong>{resolveChemicalName(chem, t.common.hcidLabel).title}</strong>
                  <EntityId kind="chemical" id={chem.id} compact />
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
              <Link key={rxn.id} className="wb-search-reaction" href={`/reaction/${rxn.id}`}>
                <EntityId kind="reaction" id={rxn.id} compact />
                <small>{rxn.doi || rxn.ord_id || rxn.dataset_name || ""}</small>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* 更多结果跳主站搜索页 */}
      {submitted && state === "ready" && total != null && total > 30 && (
        <Link className="wb-home-more-search" href={`/search?q=${encodeURIComponent(query)}&mode=${mode}`}>
          {t.me.homeViewAll} ({total})
        </Link>
      )}
    </section>
  );
}
