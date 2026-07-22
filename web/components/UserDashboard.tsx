"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { EntityId } from "@/components/EntityId";
import { PersonList, type PersonSummary } from "@/components/PersonList";
import { reactionSvgUrl } from "@/lib/api";

type LoadState = "loading" | "ready" | "error";
export type DashboardTab = "mine" | "saved" | "activity" | "followers" | "following";
export type ReactionVisibility = "all" | "public" | "private";
export type SavedKind = "chemicals" | "reactions";
type Counts = { public_reactions: number; private_reactions: number; following: number; followers: number; chemicals: number; reactions: number; unread: number };
type Summary = { username: string; display_name: string; bio: string | null; avatar_url: string | null; created_at: string; counts: Counts };
type Reaction = { id: number; reaction_smiles: string; visibility?: "public" | "private"; updated_at?: string; followers?: number };
type ReactionResponse = { items: Reaction[]; counts: { all: number; public: number; private: number }; page: number; page_size: number };
type ChemicalFollow = { id: number; preferred_name: string | null; iupac_name: string | null; smiles: string | null };
type PageResponse<T> = { items: T[]; total: number; page: number; page_size: number };
type Notice = { id: number; event_type: "new_reaction"; reaction_id: number; actor_display_name: string | null; created_at: string; read_at: string | null };

const emptyPage = <T,>(): PageResponse<T> => ({ items: [], total: 0, page: 1, page_size: 40 });
const emptyReactions = (): ReactionResponse => ({ items: [], counts: { all: 0, public: 0, private: 0 }, page: 1, page_size: 20 });

export function UserDashboard({ activeTab, page, visibility, savedKind }: {
  activeTab: DashboardTab;
  page: number;
  visibility: ReactionVisibility;
  savedKind: SavedKind;
}) {
  const { user, ready: authReady } = useAccount();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryState, setSummaryState] = useState<LoadState>("loading");
  const [contentState, setContentState] = useState<LoadState>("loading");
  const [reactionData, setReactionData] = useState<ReactionResponse>(emptyReactions());
  const [chemicals, setChemicals] = useState<PageResponse<ChemicalFollow>>(emptyPage<ChemicalFollow>());
  const [savedReactions, setSavedReactions] = useState<PageResponse<Reaction>>(emptyPage<Reaction>());
  const [notices, setNotices] = useState<Notice[]>([]);
  const [people, setPeople] = useState<PageResponse<PersonSummary>>(emptyPage<PersonSummary>());

  useEffect(() => {
    if (!user) return;
    let active = true;
    setSummaryState("loading");
    void fetch("/api/users/me/dashboard", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error();
      const value = await response.json() as Summary;
      if (active) { setSummary(value); setSummaryState("ready"); }
    }).catch(() => { if (active) setSummaryState("error"); });
    return () => { active = false; };
  }, [user]);

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
        response = await fetch("/api/users/me/notifications?limit=100", { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as Notice[];
        if (active) {
          setNotices(value);
          if (value.some((item) => !item.read_at)) {
            void fetch("/api/users/me/notifications/read", { method: "POST" }).then((readResponse) => {
              if (readResponse.ok && active) {
                setNotices((items) => items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() })));
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

  if (authReady && !user) return <div className="auth-required"><div><strong>请先登录</strong><span>登录后管理自己的反应记录和收藏。</span></div><Link href="/login?next=%2Fme">登录或注册</Link></div>;
  if (!user) return <p className="context-loading">正在读取账号…</p>;

  const counts = summary?.counts;
  const reactionTotal = counts ? counts.public_reactions + counts.private_reactions : null;
  const savedTotal = counts ? counts.chemicals + counts.reactions : null;

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

  return <>
    <header className="profile-header center-profile-header">
      <div className="profile-avatar">{(summary?.avatar_url || user.avatar_url) ? <img src={summary?.avatar_url || user.avatar_url || ""} alt="" /> : (summary?.display_name || user.display_name).slice(0, 1)}</div>
      <div className="profile-primary">
        <p className="page-kicker">个人中心</p>
        <h1>{summary?.display_name || user.display_name}</h1>
        <p className="profile-username">@{summary?.username || user.username}</p>
        {summary?.created_at && <p className="profile-joined">加入时间：{new Date(summary.created_at).toLocaleDateString("zh-CN")}</p>}
        <div className="profile-counts profile-count-links">
          <Link className={activeTab === "following" ? "active" : ""} href="/me?tab=following"><strong>{counts?.following ?? "—"}</strong><span>关注</span></Link>
          <Link className={activeTab === "followers" ? "active" : ""} href="/me?tab=followers"><strong>{counts?.followers ?? "—"}</strong><span>粉丝</span></Link>
        </div>
      </div>
      <div className="profile-center-actions"><Link className="button primary" href="/submit">新建反应记录</Link><Link className="button secondary" href="/me/settings/api-tokens">AI 授权</Link></div>
    </header>

    <div className="dashboard-shell">
      <nav className="dashboard-nav profile-tabs" aria-label="个人中心内容">
        <Link href="/me" className={activeTab === "mine" ? "active" : ""}><span>我的反应</span><em>{reactionTotal ?? "—"}</em></Link>
        <Link href="/me?tab=saved" className={activeTab === "saved" ? "active" : ""}><span>我的收藏</span><em>{savedTotal ?? "—"}</em></Link>
        <Link href="/me?tab=activity" className={activeTab === "activity" ? "active" : ""}><span>关注动态</span>{Boolean(counts?.unread) && <em className="unread-count">{counts?.unread}</em>}</Link>
      </nav>

      <main className="dashboard-panel">
        {summaryState === "error" && <p className="profile-summary-error">数据概况暂时无法读取。</p>}
        {activeTab === "mine" && <MyReactions data={reactionData} state={contentState} visibility={visibility} page={page} />}
        {activeTab === "saved" && <SavedData chemicals={chemicals} reactions={savedReactions} state={contentState} kind={savedKind} page={page} />}
        {activeTab === "activity" && <Activity notices={notices} state={contentState} />}
        {(activeTab === "followers" || activeTab === "following") && <Relationships data={people} state={contentState} kind={activeTab} page={page} onFollowChange={relationshipChanged} />}
      </main>
    </div>
  </>;
}

function MyReactions({ data, state, visibility, page }: { data: ReactionResponse; state: LoadState; visibility: ReactionVisibility; page: number }) {
  const labels: Record<ReactionVisibility, string> = { all: "全部", private: "私有", public: "公开" };
  const subtitle: Record<ReactionVisibility, string> = { all: "你通过网页或 AI 保存的全部反应记录", private: "仅当前账号可以查看", public: "会显示在你的公开主页" };
  const total = data.counts[visibility];
  return <section>
    <PanelHeading title="我的反应" subtitle={subtitle[visibility]} count={state === "ready" ? total : "—"} unit="条" />
    <nav className="dashboard-filters" aria-label="反应可见性筛选">{(["all", "private", "public"] as ReactionVisibility[]).map((value) => <Link href={value === "all" ? "/me" : `/me?visibility=${value}`} className={visibility === value ? "active" : ""} key={value}>{labels[value]}</Link>)}</nav>
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}
    {state === "ready" && (data.items.length ? <ReactionCards items={data.items} editable /> : <DashboardEmpty text={visibility === "all" ? "还没有保存反应记录。" : `还没有${labels[visibility]}反应记录。`} action />)}
    {state === "ready" && total > data.page_size && <Pagination page={page} pageSize={data.page_size} total={total} href={(value) => {
      const filter = visibility === "all" ? "" : `visibility=${visibility}`;
      return `/me?${[filter, value > 1 ? `page=${value}` : ""].filter(Boolean).join("&")}`.replace(/\?$/, "");
    }} />}
  </section>;
}

function SavedData({ chemicals, reactions, state, kind, page }: { chemicals: PageResponse<ChemicalFollow>; reactions: PageResponse<Reaction>; state: LoadState; kind: SavedKind; page: number }) {
  const data = kind === "chemicals" ? chemicals : reactions;
  return <section>
    <PanelHeading title="我的收藏" subtitle="保存需要继续查阅的公开数据" count={state === "ready" ? data.total : "—"} unit={kind === "chemicals" ? "个" : "条"} />
    <nav className="dashboard-filters" aria-label="收藏类型筛选"><Link href="/me?tab=saved" className={kind === "chemicals" ? "active" : ""}>化合物</Link><Link href="/me?tab=saved&kind=reactions" className={kind === "reactions" ? "active" : ""}>反应</Link></nav>
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}
    {state === "ready" && kind === "chemicals" && (chemicals.items.length ? <div className="followed-entity-list">{chemicals.items.map((item) => <Link href={`/chemical/${item.id}`} key={item.id}><EntityId kind="chemical" id={item.id} compact /><span><strong>{item.preferred_name || item.iupac_name || "未命名化合物"}</strong>{item.smiles && <small>{item.smiles}</small>}</span><em>查看</em></Link>)}</div> : <DashboardEmpty text="还没有收藏化合物。" />)}
    {state === "ready" && kind === "reactions" && (reactions.items.length ? <ReactionCards items={reactions.items} /> : <DashboardEmpty text="还没有收藏反应。" />)}
    {state === "ready" && data.total > data.page_size && <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => `/me?tab=saved${kind === "reactions" ? "&kind=reactions" : ""}&page=${value}`} />}
  </section>;
}

function ReactionCards({ items, editable = false }: { items: Reaction[]; editable?: boolean }) { return <div className="repository-grid">{items.map((item) => <article key={item.id}>
  <header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link>{item.updated_at && <span>{new Date(item.updated_at).toLocaleDateString("zh-CN")}</span>}</header>
  <Link className="repository-scheme" href={`/reaction/${item.id}`}><img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link>
  <footer><span>{item.visibility === "private" ? "仅自己可见" : editable ? `公开记录 · ${item.followers || 0} 人收藏` : "公开记录"}</span>{editable ? <Link href={`/submit?reaction=${item.id}`}>编辑</Link> : <Link href={`/reaction/${item.id}`}>查看</Link>}</footer>
</article>)}</div>; }

function Activity({ notices, state }: { notices: Notice[]; state: LoadState }) { return <section><PanelHeading title="关注动态" subtitle="你关注的用户新建公开反应后显示在这里" />
  {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}{state === "ready" && (notices.length ? <div className="notification-list">{notices.map((item) => <Link href={`/reaction/${item.reaction_id}`} key={item.id}><span><strong>{item.actor_display_name || "关注用户"} 新建了公开反应</strong><small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></span><EntityId kind="reaction" id={item.reaction_id} compact /></Link>)}</div> : <DashboardEmpty text="关注的用户新建公开反应后，会显示在这里。" />)}
</section>; }

function Relationships({ data, state, kind, page, onFollowChange }: {
  data: PageResponse<PersonSummary>;
  state: LoadState;
  kind: "followers" | "following";
  page: number;
  onFollowChange: (person: PersonSummary, following: boolean) => void;
}) {
  const title = kind === "followers" ? "粉丝" : "关注";
  return <section>
    <PanelHeading title={title} subtitle={kind === "followers" ? "关注你的人，可以查看主页或回关" : "你正在关注的人，可以查看主页或取消关注"} count={state === "ready" ? data.total : "—"} unit="人" />
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}
    {state === "ready" && <PersonList items={data.items} empty={kind === "followers" ? "还没有粉丝。" : "还没有关注用户。"} kind={kind} onFollowChange={onFollowChange} />}
    {state === "ready" && data.total > data.page_size && <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => `/me?tab=${kind}${value > 1 ? `&page=${value}` : ""}`} />}
  </section>;
}

function PanelHeading({ title, subtitle, count, unit = "" }: { title: string; subtitle?: string; count?: number | string; unit?: string }) { return <div className="dashboard-panel-heading"><div><h2>{title}</h2>{subtitle && <span>{subtitle}</span>}</div>{count !== undefined && <strong>{count} {unit}</strong>}</div>; }
function Pagination({ page, pageSize, total, href }: { page: number; pageSize: number; total: number; href: (page: number) => string }) { const pages = Math.ceil(total / pageSize); return <nav className="profile-pagination" aria-label="分页">{page > 1 ? <Link href={href(page - 1)}>上一页</Link> : <span />}<small>{page} / {pages}</small>{page < pages ? <Link href={href(page + 1)}>下一页</Link> : <span />}</nav>; }
function DashboardEmpty({ text, action = false }: { text: string; action?: boolean }) { return <div className="dashboard-empty"><p>{text}</p>{action && <Link className="button secondary small" href="/submit">新建反应记录</Link>}</div>; }
function PanelLoading() { return <p className="panel-state">正在读取…</p>; }
function PanelError() { return <p className="panel-state error">数据读取失败，请刷新后重试。</p>; }
