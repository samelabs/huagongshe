"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { PersonList, type PersonSummary } from "@/components/PersonList";
import t from "@/lib/i18n";
import { ActivityPanel } from "./panels/ActivityPanel";
import { RelationshipsPanel } from "./panels/RelationshipsPanel";
import { ReactionsPanel } from "./panels/ReactionsPanel";
import { SavedPanel } from "./panels/SavedPanel";
import { WorkbenchNav } from "./WorkbenchNav";
import type {
  ChemicalFollow,
  DashboardTab,
  LoadState,
  NoticeResponse,
  PageResponse,
  Reaction,
  ReactionResponse,
  ReactionVisibility,
  SavedKind,
  Summary,
} from "./types";

const emptyPage = <T,>(): PageResponse<T> => ({ items: [], total: 0, page: 1, page_size: 40 });
const emptyReactions = (): ReactionResponse => ({ items: [], counts: { all: 0, public: 0, private: 0 }, page: 1, page_size: 20 });
const emptyNotices = (): NoticeResponse => ({ items: [], total: 0, page: 1, page_size: 50 });

export function DashboardLayout({ activeTab, page, visibility, savedKind, initialSummary }: {
  activeTab: DashboardTab;
  page: number;
  visibility: ReactionVisibility;
  savedKind: SavedKind;
  initialSummary?: Summary | null;
}) {
  const { user, ready: authReady } = useAccount();
  const [summary, setSummary] = useState<Summary | null>(initialSummary ?? null);
  const [summaryState, setSummaryState] = useState<LoadState>(initialSummary ? "ready" : "loading");
  const [contentState, setContentState] = useState<LoadState>("loading");
  const [reactionData, setReactionData] = useState<ReactionResponse>(emptyReactions());
  const [chemicals, setChemicals] = useState<PageResponse<ChemicalFollow>>(emptyPage<ChemicalFollow>());
  const [savedReactions, setSavedReactions] = useState<PageResponse<Reaction>>(emptyPage<Reaction>());
  const [notices, setNotices] = useState<NoticeResponse>(emptyNotices());
  const [people, setPeople] = useState<PageResponse<PersonSummary>>(emptyPage<PersonSummary>());

  useEffect(() => {
    if (!user || initialSummary) return;
    let active = true;
    setSummaryState("loading");
    void fetch("/api/users/me/dashboard", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error();
      const value = await response.json() as Summary;
      if (active) { setSummary(value); setSummaryState("ready"); }
    }).catch(() => { if (active) setSummaryState("error"); });
    return () => { active = false; };
  }, [user, initialSummary]);

  useEffect(() => {
    if (!user) return;
    const username = user.username;
    let active = true;
    setContentState("loading");
    async function load() {
      let response: Response;
      if (activeTab === "mine") {
        response = await fetch(`/api/users/me/reactions?visibility=${visibility}&page=${page}&page_size=20`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as ReactionResponse;
        if (active) setReactionData(value);
      } else if (activeTab === "saved" && savedKind === "chemicals") {
        response = await fetch(`/api/users/me/follows/chemicals?page=${page}&page_size=40`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as PageResponse<ChemicalFollow>;
        if (active) setChemicals(value);
      } else if (activeTab === "saved") {
        response = await fetch(`/api/users/me/follows/reactions?page=${page}&page_size=20`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as PageResponse<Reaction>;
        if (active) setSavedReactions(value);
      } else if (activeTab === "activity") {
        response = await fetch(`/api/users/me/notifications?page=${page}&page_size=50`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as NoticeResponse;
        if (active) {
          setNotices(value);
          if (page === 1 && value.items.some((item) => !item.read_at)) {
            void fetch("/api/users/me/notifications/read", { method: "POST" }).then((readResponse) => {
              if (readResponse.ok && active) {
                setNotices((current) => ({ ...current, items: current.items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() })) }));
                setSummary((current) => current ? { ...current, counts: { ...current.counts, unread: 0 } } : current);
              }
            });
          }
        }
      } else {
        response = await fetch(`/api/users/${encodeURIComponent(username)}/${activeTab}?page=${page}&page_size=40`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as PageResponse<PersonSummary>;
        if (active) setPeople(value);
      }
      if (active) setContentState("ready");
    }
    void load().catch(() => { if (active) setContentState("error"); });
    return () => { active = false; };
  }, [activeTab, page, savedKind, user, visibility]);

  if (authReady && !user) return <div className="wb-auth-required"><div><strong>{t.common.loginRequired}</strong><span>{t.common.loginHint}</span></div><Link href="/login?next=%2Faichem">{t.common.loginOrRegister}</Link></div>;
  if (!user) return <p className="wb-loading">{t.common.loadingAccount}</p>;

  const counts = summary?.counts;

  function relationshipChanged(person: PersonSummary, following: boolean) {
    if (person.is_following === following) return;
    setPeople((current) => ({
      ...current,
      items: activeTab === "following" && !following
        ? current.items.filter((item) => item.username !== person.username)
        : current.items.map((item) => item.username === person.username ? { ...item, is_following: following } : item),
      total: activeTab === "following" && !following ? Math.max(current.total - 1, 0) : current.total,
    }));
    setSummary((current) => current ? {
      ...current,
      counts: {
        ...current.counts,
        following: Math.max(current.counts.following + (following ? 1 : -1), 0),
      },
    } : current);
  }

  return (
    <div className="wb">
      {/* 用户信息条 */}
      <div className="wb-bar">
        <div className="wb-bar-avatar">
          {(summary?.avatar_url || user.avatar_url)
            ? <img src={summary?.avatar_url || user.avatar_url || ""} alt="" />
            : <span>{(summary?.display_name || user.display_name).slice(0, 1)}</span>}
        </div>
        <div className="wb-bar-info">
          <strong>{summary?.display_name || user.display_name}</strong>
          <span>@{summary?.username || user.username}</span>
        </div>
        <div className="wb-bar-actions">
          <Link className="wb-btn wb-btn-primary" href="/submit">{t.me.newReaction}</Link>
          <Link className="wb-btn wb-btn-ghost" href="/me/settings/api-tokens">{t.me.aiAssistant}</Link>
        </div>
      </div>

      {/* 主体：导航 + 内容 */}
      <div className="wb-body">
        <WorkbenchNav counts={counts} activeTab={activeTab} />

        {/* 右侧内容 */}
        <main className="wb-main">
          {summaryState === "error" && <p className="wb-error">{t.me.errSummary}</p>}
          {activeTab === "mine" && <ReactionsPanel data={reactionData} state={contentState} visibility={visibility} page={page} />}
          {activeTab === "saved" && <SavedPanel chemicals={chemicals} reactions={savedReactions} state={contentState} kind={savedKind} page={page} />}
          {activeTab === "activity" && <ActivityPanel notices={notices} state={contentState} page={page} />}
          {(activeTab === "followers" || activeTab === "following") && <RelationshipsPanel data={people} state={contentState} kind={activeTab} page={page} onFollowChange={relationshipChanged} />}
        </main>
      </div>
    </div>
  );
}
