"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { apiGet, molSvgUrl } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import type { Locale } from "@/lib/i18n/locales";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Tabs } from "@/components/ui/Tabs";
import { IconNote, IconPlus, IconSearch, IconCalc, IconSparkle, IconPlug, GlyphChem, GlyphRx } from "@/components/ui/icons";
import { ActivityFeedCard, PanelError, PanelLoading, ReactionRow, SlowNotice, VisibilityTag, WbListRow, noteHeadline, relativeTime } from "../shared";
import type { Counts, LoadState, NoteResponse, PageResponse, Reaction, ReactionResponse } from "../types";
import type { ChemicalFollow, Notice } from "../types";
import { Input } from "@/components/ui/Field";

/**
 * 工作台概览（DESIGN_SYSTEM 6.7：工具在左，社交在右）。
 *
 * 数据全部来自现有读接口（SSR 预取传入，失败的流客户端补拉）：
 *  - 我的内容：/users/me/notes、/users/me/reactions、/users/me/follows/chemicals
 *  - 「最近」= 三个流按时间合并取前 8
 *  - 关注动态：/users/me/notifications（v1.7 只有 new_reaction 事件）
 *  - 动态卡片收藏初始态：/users/me/follows/reactions 的 id 集
 * 统计/问候用 counts + 本地时间；删除旧版三个统计卡与「连接 AI 助手」
 * 大提示框（入口收进快捷入口）。
 */

type FeedProps = {
  counts: Counts | null;
  initialNotes: NoteResponse | null;
  initialReactions: ReactionResponse | null;
  initialFavorites: PageResponse<ChemicalFollow> | null;
  initialNotices: { items: Notice[]; total: number } | null;
  initialFavoredIds: number[] | null;
};

type RecentItem =
  | { kind: "note"; id: number; at: string; note: NoteResponse["items"][number] }
  | { kind: "reaction"; id: number; at: string; reaction: Reaction }
  | { kind: "saved"; id: number; at: string; chemical: ChemicalFollow };

export function HomePanel({ counts, initialNotes, initialReactions, initialFavorites, initialNotices, initialFavoredIds }: FeedProps) {
  const t = useDictionary();
  const locale: Locale = useLocale();
  const { user } = useAccount();
  const router = useRouter();
  const [recentNotes, setRecentNotes] = useState<NoteResponse | null>(initialNotes ?? null);
  const [recent, setRecent] = useState<ReactionResponse | null>(initialReactions ?? null);
  const [favorites, setFavorites] = useState<PageResponse<ChemicalFollow> | null>(initialFavorites ?? null);
  const [notices, setNotices] = useState<FeedProps["initialNotices"]>(initialNotices ?? null);
  const [favoredIds, setFavoredIds] = useState<Set<number>>(new Set(initialFavoredIds ?? []));
  const [state, setState] = useState<LoadState>(
    initialNotes && initialReactions && initialFavorites ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");
  const [mineTab, setMineTab] = useState("recent");

  // 问候语按访问者本地时间（水合后计算，避免 SSR 时区不一致）
  const [greeting, setGreeting] = useState<string | null>(null);
  useEffect(() => {
    const hour = new Date().getHours();
    setGreeting(hour < 12 ? t.me.greetingMorning : hour < 18 ? t.me.greetingAfternoon : t.me.greetingEvening);
  }, [t]);

  // SSR 流失败时客户端补拉（与旧版 Home 相同的降级策略）；
  // FX-16：重试 nonce 重新触发补拉（effect 内部对已有数据做空跳过，幂等）
  const [reloadNonce, setReloadNonce] = useState(0);
  useEffect(() => {
    let active = true;
    const jobs: Promise<unknown>[] = [];
    if (!recentNotes) jobs.push(apiGet<NoteResponse>("/users/me/notes?visibility=all&page=1&page_size=8").then(setRecentNotes));
    if (!recent) jobs.push(apiGet<ReactionResponse>("/users/me/reactions?visibility=all&page=1&page_size=8").then(setRecent));
    if (!favorites) jobs.push(apiGet<PageResponse<ChemicalFollow>>("/users/me/follows/chemicals?page=1&page_size=8").then(setFavorites));
    if (!notices) jobs.push(apiGet<FeedProps["initialNotices"]>("/users/me/notifications?page=1&page_size=5").then(setNotices));
    if (initialFavoredIds == null) {
      jobs.push(apiGet<PageResponse<Reaction>>("/users/me/follows/reactions?page=1&page_size=50")
        .then((page) => setFavoredIds(new Set(page.items.map((item) => item.id)))));
    }
    if (jobs.length === 0) return;
    Promise.all(jobs)
      .then(() => { if (active) setState("ready"); })
      .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadNonce]);

  // 「最近」= 反应/笔记/收藏按时间合并，取前 8
  const recentItems = useMemo<RecentItem[]>(() => {
    const notes = (recentNotes?.items ?? []).map((note) => ({ kind: "note" as const, id: note.id, at: note.updated_at, note }));
    const reactions = (recent?.items ?? []).map((reaction) => ({ kind: "reaction" as const, id: reaction.id, at: reaction.updated_at ?? "", reaction }));
    const saved = (favorites?.items ?? []).map((chemical) => ({ kind: "saved" as const, id: chemical.id, at: chemical.created_at ?? "", chemical }));
    return [...notes, ...reactions, ...saved]
      .filter((item) => item.at)
      .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
      .slice(0, 8);
  }, [recentNotes, recent, favorites]);

  if (state === "loading") return <section className="wb-panel"><PanelLoading variant="list" rows={4} /><SlowNotice active onRetry={() => setReloadNonce((n) => n + 1)} /></section>;
  if (state === "error") return <PanelError error={error} />;
  if (!counts || !user) return <PanelError />;

  const notes = recentNotes?.items ?? [];
  const reactions = recent?.items ?? [];
  const savedItems = favorites?.items ?? [];
  const feedItems = (notices?.items ?? []).slice(0, 5);
  const name = user.display_name || `@${user.username}`;

  function goSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    router.push(withLocale(`/search?q=${encodeURIComponent(q)}`, locale));
  }

  const mineTabs = [
    { id: "recent", label: t.me.mineTabRecent },
    { id: "reactions", label: t.me.mineTabReactions, count: counts.public_reactions + counts.private_reactions },
    { id: "notes", label: t.me.mineTabNotes, count: counts.notes },
    { id: "saved", label: t.me.mineTabSaved, count: counts.chemicals + counts.reactions },
  ];
  const viewAllHref = mineTab === "reactions" ? "/aichem?tab=mine" : mineTab === "notes" ? "/aichem?tab=notes" : mineTab === "saved" ? "/aichem?tab=saved" : "/aichem?tab=mine";

  const quickLinks: { href: string; icon: React.ReactNode; label: string }[] = [
    { href: "/aichem?tab=stoich", icon: <IconCalc />, label: t.me.tabStoich },
    { href: "/search?mode=substructure", icon: <IconSearch />, label: t.me.quickSubstructure },
    { href: "/aichem?tab=skills", icon: <IconSparkle />, label: t.me.quickSkills },
    { href: "/mcp-guide", icon: <IconPlug />, label: t.me.homeGuideTitle },
  ];

  return (
    <div className="wb-home2">
      {/* ── 标题行（跨两列）：问候 + 状态 ｜ 新建笔记 / 新建反应 ── */}
      <header className="wb-home2-head">
        <div className="wb-home2-title">
          <h2>{greeting ? t.me.greetingTitle(greeting, name) : name}</h2>
          <p>{counts.unread > 0 ? t.me.homeStatusUnread(counts.unread) : t.me.homeStatusIdle}</p>
        </div>
        <div className="wb-home2-actions">
          <Button variant="secondary" href={withLocale("/aichem?tab=notes&new=1", locale)}>
            <IconNote />{t.me.navNewNote}
          </Button>
          <Button variant="primary" href={withLocale("/submit", locale)}>
            <IconPlus />{t.me.navNewReaction}
          </Button>
        </div>
      </header>

      {/* ── 概览内容列（工具在左，社交统一由外层 WorkbenchSocialRail 提供） ── */}
      <div className="wb-home2-col-main">
        {/* ── 快速检索 + 快捷入口 ── */}
        <section className="wb-card wb-home2-quick" data-area="quick">
          <form method="post" className="wb-home2-search" onSubmit={goSearch}>
            <div className="wb-search-field">
              <svg className="wb-search-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <line x1="21" y1="21" x2="16.5" y2="16.5" />
              </svg>
              <Input
                type="text"
                enterKeyHint="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t.me.homeSearchPlaceholder}
                aria-label={t.me.homeSearchButton}
                autoComplete="off"
                spellCheck={false}
              />
              <Button type="submit" variant="secondary" size="sm" className="wb-search-submit">{t.me.homeSearchButton}</Button>
            </div>
          </form>
          <div className="wb-quick-links">
            {quickLinks.map((item) => (
              <Link key={item.href} href={withLocale(item.href, locale)} className="wb-quick-link">
                <span className="wb-quick-link-icon" aria-hidden="true">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            ))}
          </div>
        </section>

        {/* ── 我的内容 ── */}
        <section className="wb-card wb-home2-mine" data-area="mine">
          <div className="wb-card-head">
            <h3>{t.me.mineTitle}</h3>
            <Link href={withLocale(viewAllHref, locale)}>{t.me.mineAll}</Link>
          </div>
          <Tabs tabs={mineTabs} value={mineTab} onChange={setMineTab} ariaLabel={t.me.mineTitle} />
          <div className="wb-row-list">
            {mineTab === "recent" && (recentItems.length > 0
              ? recentItems.map((item) => <RecentRow key={`${item.kind}-${item.id}`} item={item} t={t} locale={locale} />)
              : <EmptyState icon={<IconNote />} title={t.me.mineEmptyRecent}>
                  <Button variant="tonal" size="sm" href={withLocale("/submit", locale)}>{t.me.navNewReaction}</Button>
                </EmptyState>)}
            {mineTab === "reactions" && (reactions.length > 0
              ? reactions.map((item) => <ReactionRow key={item.id} item={item} t={t} locale={locale} />)
              : <EmptyState icon={<GlyphRx />} title={t.me.emptyReactions}>
                  <Button variant="tonal" size="sm" href={withLocale("/submit", locale)}>{t.me.navNewReaction}</Button>
                </EmptyState>)}
            {mineTab === "notes" && (notes.length > 0
              ? notes.map((note) => <NoteRow key={note.id} note={note} t={t} locale={locale} />)
              : <EmptyState icon={<IconNote />} title={t.me.notesEmpty}>
                  <Button variant="tonal" size="sm" href={withLocale("/aichem?tab=notes&new=1", locale)}>{t.me.navNewNote}</Button>
                </EmptyState>)}
            {mineTab === "saved" && (savedItems.length > 0
              ? savedItems.map((chemical) => <SavedRow key={chemical.id} chemical={chemical} t={t} locale={locale} />)
              : <EmptyState icon={<GlyphChem />} title={t.me.emptyChemicals}>
                  <Button variant="tonal" size="sm" href={withLocale("/aichem?tab=search", locale)}>{t.me.tabSearch}</Button>
                </EmptyState>)}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ── 行组件：概览「我的内容」行 = 面板列表行（WbListRow，DESIGN_SYSTEM 6.7）── */

function RecentRow({ item, t, locale }: { item: RecentItem; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  if (item.kind === "note") return <NoteRow note={item.note} t={t} locale={locale} />;
  if (item.kind === "reaction") return <ReactionRow item={item.reaction} t={t} locale={locale} />;
  return <SavedRow chemical={item.chemical} t={t} locale={locale} />;
}

function NoteRow({ note, t, locale }: { note: NoteResponse["items"][number]; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  return (
    <WbListRow
      href={`/note/${note.id}`}
      icon={<IconNote />}
      title={noteHeadline(note.content, { fallbackTitle: t.notes.untitled })}
      meta={
        <>
          <VisibilityTag visibility={note.visibility} t={t} />
          {note.chemical_ids.slice(0, 2).map((cid) => <EntityBadge key={`c${cid}`} kind="chemical" id={cid} size="xs" ariaLabel={t.common.hcidLabel(cid)} />)}
          {note.reaction_ids.slice(0, 2).map((rid) => <EntityBadge key={`r${rid}`} kind="reaction" id={rid} size="xs" ariaLabel={t.common.hridLabel(rid)} />)}
        </>
      }
      side={<time dateTime={note.updated_at}>{relativeTime(note.updated_at, locale)}</time>}
    />
  );
}

function SavedRow({ chemical, t, locale }: { chemical: ChemicalFollow; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  const { title } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  return (
    <WbListRow
      href={`/chemical/${chemical.id}`}
      thumb={
        // eslint-disable-next-line @next/next/no-img-element
        <img src={molSvgUrl(chemical.id)} width={36} height={36} alt="" loading="lazy" />
      }
      title={title}
      meta={
        <EntityBadge kind="chemical" id={chemical.id} size="xs" ariaLabel={t.common.hcidLabel(chemical.id)} />
      }
      side={
        <>
          {chemical.created_at && <time dateTime={chemical.created_at}>{t.me.savedAt(new Date(chemical.created_at).toLocaleDateString(locale))}</time>}
          <span>{chemical.molecular_formula ?? ""}</span>
        </>
      }
    />
  );
}
