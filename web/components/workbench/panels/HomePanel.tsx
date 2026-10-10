"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { FollowButton } from "@/components/shared/FollowButton";
import { apiGet, molSvgUrl, reactionSvgUrl } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import type { Locale } from "@/lib/i18n/locales";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Segmented } from "@/components/ui/Segmented";
import { Tabs } from "@/components/ui/Tabs";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { IconNote, IconSearch, IconCalc, IconSparkle, IconPlug, IconShare, GlyphChem, GlyphRx } from "@/components/ui/icons";
import { PanelError, PanelLoading } from "../shared";
import type { Counts, LoadState, NoteResponse, PageResponse, Reaction, ReactionResponse } from "../types";
import type { ChemicalFollow, Notice } from "../types";

/**
 * 工作台概览（§9.4 Step 8 重做：工具在左，社交在右）。
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

/** 相对时间（分钟/小时/天；超过 30 天回退绝对日期） */
function relativeTime(value: string, locale: string): string {
  const date = new Date(value).getTime();
  if (!Number.isFinite(date)) return value;
  const minutes = Math.round((Date.now() - date) / 60000);
  const fmt = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (minutes < 1) return fmt.format(0, "minute");
  if (minutes < 60) return fmt.format(-minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return fmt.format(-hours, "hour");
  const days = Math.round(hours / 24);
  if (days <= 30) return fmt.format(-days, "day");
  return new Date(value).toLocaleDateString(locale);
}

/** 笔记标题行：首个非空行（≤60 字） */
function noteHeadline(content: string): string {
  const first = content.split("\n").map((l) => l.trim()).find((l) => l.length > 0) ?? "";
  return first.length > 60 ? `${first.slice(0, 60)}…` : first;
}

export function HomePanel({ counts, initialNotes, initialReactions, initialFavorites, initialNotices, initialFavoredIds }: FeedProps) {
  const t = useDictionary();
  const locale: Locale = useLocale();
  const { user } = useAccount();
  const router = useRouter();
  const toast = useToast();
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
  const [mobileView, setMobileView] = useState<"mine" | "feed">("mine");

  // 问候语按访问者本地时间（水合后计算，避免 SSR 时区不一致）
  const [greeting, setGreeting] = useState<string | null>(null);
  useEffect(() => {
    const hour = new Date().getHours();
    setGreeting(hour < 12 ? t.me.greetingMorning : hour < 18 ? t.me.greetingAfternoon : t.me.greetingEvening);
  }, [t]);

  // SSR 流失败时客户端补拉（与旧版 Home 相同的降级策略）
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
  }, []);

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

  if (state === "loading") return <PanelLoading variant="list" rows={4} />;
  if (state === "error") return <PanelError error={error} />;
  if (!counts || !user) return <PanelError />;

  const notes = recentNotes?.items ?? [];
  const reactions = recent?.items ?? [];
  const savedItems = favorites?.items ?? [];
  const feedItems = (notices?.items ?? []).filter((item) => item.event_type === "new_reaction").slice(0, 5);
  const name = user.display_name || `@${user.username}`;

  function goSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    router.push(withLocale(`/search?q=${encodeURIComponent(q)}`, locale));
  }

  function shareProfile() {
    const link = `${window.location.origin}${withLocale(`/user/${encodeURIComponent(user!.username)}`, locale)}`;
    void navigator.clipboard?.writeText(link);
    toast.success(t.me.profileLinkCopied);
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
    <div className="wb-home2" data-view={mobileView}>
      {/* ── 标题行（跨两列）：问候 + 状态 ｜ 新建笔记 / 新建反应 ── */}
      <header className="wb-home2-head">
        <div className="wb-home2-title">
          <h2>{greeting ? `${greeting}，${name}` : name}</h2>
          <p>{counts.unread > 0 ? t.me.homeStatusUnread(counts.unread) : t.me.homeStatusIdle}</p>
        </div>
        <div className="wb-home2-actions">
          <Button variant="secondary" href={withLocale("/aichem?tab=notes&new=1", locale)}>{t.me.navNewNote}</Button>
          <Button variant="primary" href={withLocale("/submit", locale)}>{t.me.navNewReaction}</Button>
        </div>
      </header>

      {/* ── 手机（≤640）：标题行 → 快速检索 → 2×2 快捷入口 → Segmented
          （我的内容 | 关注动态 · N）→ 列表 → 主页卡片（§9.7 / Step 9 A.3）。
          Segmented 放进 grid（data-area=switch）：手机在 quick 与 mine 之间，
          桌面由 CSS 隐藏。 ── */}
      <div className="wb-home2-grid">
        {/* ── 快速检索 + 快捷入口 ── */}
        <section className="wb-card wb-home2-quick" data-area="quick">
          <form className="wb-home2-search" onSubmit={goSearch}>
            <div className="wb-search-field">
              <svg className="wb-search-field-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <line x1="21" y1="21" x2="16.5" y2="16.5" />
              </svg>
              <input
                type="text"
                enterKeyHint="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t.me.homeSearchPlaceholder}
                aria-label={t.me.homeSearchButton}
                autoComplete="off"
                spellCheck={false}
              />
              <button type="submit" className="wb-search-submit">{t.me.homeSearchButton}</button>
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

        {/* ── 手机切换：我的内容 ↔ 关注动态（桌面隐藏，见 CSS） ── */}
        <div className="wb-home2-switch" data-area="switch">
          <Segmented
            ariaLabel={t.me.mineTitle}
            options={[
              { value: "mine", label: t.me.mineTitle },
              { value: "feed", label: t.me.mobileFeedLabel(counts.unread) },
            ]}
            value={mobileView}
            onChange={(value) => setMobileView(value)}
          />
        </div>

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

        {/* ── 我的主页卡片 ── */}
        <section className="wb-card wb-profile-card" data-area="profile">
          <div className="wb-profile-top">
            <Avatar id={user.id} name={user.display_name} src={user.avatar_url} size={40} />
            <div className="wb-profile-id">
              <strong>{user.display_name}</strong>
              <small>@{user.username}</small>
            </div>
            <Button variant="ghost" iconOnly aria-label={t.me.profileShareLabel} onClick={shareProfile}>
              <IconShare />
            </Button>
          </div>
          <div className="wb-profile-stats">
            <Link href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)}>
              <strong>{counts.public_reactions}</strong><span>{t.user.publicReactions}</span>
            </Link>
            <Link href={withLocale(`/aichem?tab=followers`, locale)}>
              <strong>{counts.followers}</strong><span>{t.user.followers}</span>
            </Link>
            <Link href={withLocale(`/aichem?tab=following`, locale)}>
              <strong>{counts.following}</strong><span>{t.user.following}</span>
            </Link>
          </div>
          <Button variant="secondary" size="sm" className="wb-profile-cta" href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)}>
            {t.me.profileViewPublic}
          </Button>
        </section>

        {/* ── 关注动态 ── */}
        <section className="wb-card wb-feed-card" data-area="feed">
          <div className="wb-card-head">
            <h3>{t.me.tabActivity}</h3>
          </div>
          {feedItems.length > 0 ? (
            <>
              <div className="wb-feed-list">
                {feedItems.map((item) => (
                  <article key={item.id} className="wb-feed-item">
                    <Avatar id={item.actor_username} name={item.actor_display_name || item.actor_username} size={32} />
                    <div className="wb-feed-body">
                      <p className="wb-feed-line">
                        {t.me.feedActor(item.actor_display_name || item.actor_username)}
                        <EntityBadge kind="reaction" id={item.reaction_id} size="xs" href={withLocale(`/reaction/${item.reaction_id}`, locale)} ariaLabel={t.common.hridLabel(item.reaction_id)} />
                      </p>
                      <time dateTime={item.created_at}>{relativeTime(item.created_at, locale)}</time>
                      <Link className="wb-feed-eq" href={withLocale(`/reaction/${item.reaction_id}`, locale)}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={reactionSvgUrl(item.reaction_id, 720, 160)} height={64} alt={t.reaction.equationAlt(item.reaction_id)} loading="lazy" />
                      </Link>
                      <div className="wb-feed-actions">
                        <FollowButton
                          endpoint={`/reactions/${item.reaction_id}/follow`}
                          initial={favoredIds.has(item.reaction_id)}
                          showCount={false}
                          label="favor"
                          variant="ghost"
                          size="sm"
                        />
                        <Button variant="ghost" size="sm" href={withLocale(`/reaction/${item.reaction_id}`, locale)}>{t.me.feedOpen}</Button>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              <Link className="wb-feed-all" href={withLocale("/aichem?tab=activity", locale)}>{t.me.feedViewAll}</Link>
            </>
          ) : (
            <EmptyState icon={<GlyphRx />} title={t.me.feedEmpty} />
          )}
        </section>
      </div>
    </div>
  );
}

/* ── 行组件 ─────────────────────────────────────────── */

function VisibilityTag({ visibility, t }: { visibility: "public" | "private"; t: ReturnType<typeof useDictionary> }) {
  return visibility === "private"
    ? <Tag>{t.common.private}</Tag>
    : <Tag tone="blue">{t.common.public}</Tag>;
}

function RecentRow({ item, t, locale }: { item: RecentItem; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  if (item.kind === "note") return <NoteRow note={item.note} t={t} locale={locale} />;
  if (item.kind === "reaction") return <ReactionRow item={item.reaction} t={t} locale={locale} />;
  return <SavedRow chemical={item.chemical} t={t} locale={locale} />;
}

function NoteRow({ note, t, locale }: { note: NoteResponse["items"][number]; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  return (
    <Link className="wb-row" href={withLocale(`/note/${note.id}`, locale)}>
      <span className="wb-row-icon note" aria-hidden="true"><IconNote /></span>
      <span className="wb-row-main">
        <span className="wb-row-title">{noteHeadline(note.content)}</span>
        <span className="wb-row-meta">
          <VisibilityTag visibility={note.visibility} t={t} />
          {note.chemical_ids.slice(0, 2).map((cid) => <EntityBadge key={`c${cid}`} kind="chemical" id={cid} size="xs" ariaLabel={t.common.hcidLabel(cid)} />)}
          {note.reaction_ids.slice(0, 2).map((rid) => <EntityBadge key={`r${rid}`} kind="reaction" id={rid} size="xs" ariaLabel={t.common.hridLabel(rid)} />)}
          <time dateTime={note.updated_at}>{relativeTime(note.updated_at, locale)}</time>
        </span>
      </span>
      <span className="wb-row-side">{new Date(note.updated_at).toLocaleDateString(locale)}</span>
    </Link>
  );
}

function ReactionRow({ item, t, locale }: { item: Reaction; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  return (
    <Link className="wb-row" href={withLocale(`/reaction/${item.id}`, locale)}>
      <span className="wb-row-icon reaction" aria-hidden="true"><GlyphRx /></span>
      <span className="wb-row-main">
        <span className="wb-row-title">
          <EntityBadge kind="reaction" id={item.id} size="sm" ariaLabel={t.common.hridLabel(item.id)} />
        </span>
        <span className="wb-row-meta">
          {item.visibility && <VisibilityTag visibility={item.visibility} t={t} />}
          <time dateTime={item.updated_at ?? undefined}>{item.updated_at ? relativeTime(item.updated_at, locale) : ""}</time>
        </span>
      </span>
      <span className="wb-row-side">{item.followers != null ? t.user.peopleCount(item.followers) : ""}</span>
    </Link>
  );
}

function SavedRow({ chemical, t, locale }: { chemical: ChemicalFollow; t: ReturnType<typeof useDictionary>; locale: Locale }) {
  const { title } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  return (
    <Link className="wb-row" href={withLocale(`/chemical/${chemical.id}`, locale)}>
      <span className="wb-row-icon saved" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={molSvgUrl(chemical.id, 72, 56)} width={36} height={36} alt="" loading="lazy" />
      </span>
      <span className="wb-row-main">
        <span className="wb-row-title">{title}</span>
        <span className="wb-row-meta">
          <EntityBadge kind="chemical" id={chemical.id} size="xs" ariaLabel={t.common.hcidLabel(chemical.id)} />
          {chemical.created_at && <time dateTime={chemical.created_at}>{t.me.savedAt(new Date(chemical.created_at).toLocaleDateString(locale))}</time>}
        </span>
      </span>
      <span className="wb-row-side">{chemical.molecular_formula ?? ""}</span>
    </Link>
  );
}
