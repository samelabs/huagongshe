"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { EntityId } from "@/components/shared/EntityId";
import { useAccount } from "@/components/shared/AccountContext";
import { apiGet, reactionSvgUrl } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { PanelLoading, PanelError } from "../shared";
import type { Counts, LoadState, ReactionResponse } from "../types";

/**
 * 工作台首页 — 概览面板
 * 问候语 + 统计卡片 + 最近反应
 * counts 和 initialReactions 由 WorkbenchLayout 从 page.tsx SSR 预取传入
 */
export function HomePanel({ counts, initialReactions }: {
  counts: Counts | null;
  initialReactions?: ReactionResponse | null;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const { user } = useAccount();
  const router = useRouter();
  const [recent, setRecent] = useState<ReactionResponse | null>(initialReactions ?? null);
  const [state, setState] = useState<LoadState>(initialReactions ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    // SSR 预取了数据时跳过首次 fetch
    if (initialReactions) return;
    let active = true;
    apiGet<ReactionResponse>("/users/me/reactions?visibility=public&page=1&page_size=4")
      .then((r) => { if (!active) return; setRecent(r); setState("ready"); })
      .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    return () => { active = false; };
  }, []);

  if (state === "loading") return <PanelLoading variant="grid" rows={2} />;
  if (state === "error") return <PanelError error={error} />;
  if (!counts) return <PanelError />;

  const c = counts;
  const name = user?.display_name || "";
  const reactions = recent?.items ?? [];

  function goSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    router.push(withLocale(`/aichem?tab=search&q=${encodeURIComponent(q)}`, locale));
  }

  return (
    <section className="wb-panel wb-home">
      {/* 欢迎词 */}
      <div className="wb-home-hero">
        <h2>{t.me.homeGreeting(name)}</h2>
        <p>{t.me.homeHint}</p>
      </div>

      {/* 搜索框 */}
      <form className="wb-search-form" onSubmit={goSearch}>
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
            placeholder={t.me.homeSearchPlaceholder}
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" className="wb-search-submit">{t.me.homeSearchButton}</button>
        </div>
      </form>

      {/* 统计卡片 */}
      <div className="wb-home-stats">
        <Link className="wb-home-stat" href="/aichem?tab=mine">
          <strong>{c.public_reactions + c.private_reactions}</strong>
          <span>{t.me.tabReactions}</span>
        </Link>
        <Link className="wb-home-stat" href="/aichem?tab=saved">
          <strong>{c.chemicals + c.reactions}</strong>
          <span>{t.me.tabSaved}</span>
        </Link>
        <Link className="wb-home-stat" href="/aichem?tab=activity">
          <strong>{c.unread || 0}</strong>
          <span>{t.me.tabActivity}</span>
        </Link>
      </div>

      {/* AI 指南入口 */}
      <Link className="wb-home-guide" href="/mcp-guide">
        <div className="wb-home-guide-body">
          <h3>{t.me.homeGuideTitle}</h3>
          <p>{t.me.homeGuideDesc}</p>
        </div>
        <span className="wb-home-guide-cta">{t.me.homeGuideCta}</span>
      </Link>

      {/* 最近反应 */}
      {reactions.length > 0 && (
        <div className="wb-home-recent">
          <div className="wb-home-recent-head">
            <h3>{t.me.homeRecentReactions}</h3>
            <Link href="/aichem?tab=mine">{t.me.homeViewAll}</Link>
          </div>
          <div className="wb-grid">
            {reactions.map((item) => (
              <article key={item.id}>
                <header>
                  <Link href={withLocale(`/reaction/${item.id}`, locale)}><EntityId kind="reaction" id={item.id} compact ariaLabel={t.common.hridLabel(item.id)} /></Link>
                  {item.updated_at && <span>{new Date(item.updated_at).toLocaleDateString(locale)}</span>}
                </header>
                <Link className="wb-card-img" href={withLocale(`/reaction/${item.id}`, locale)}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={t.reaction.equationAlt(item.id)} />
                </Link>
                <footer>
                  <span>{item.visibility === "private" ? t.me.privateVisible : t.common.public}</span>
                  <Link href={withLocale(`/reaction/${item.id}`, locale)}>{t.common.view}</Link>
                </footer>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
