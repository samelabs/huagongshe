"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EntityId } from "@/components/EntityId";
import { reactionSvgUrl, type User } from "@/lib/api";

type Reaction = {
  id: number;
  reaction_smiles: string;
  visibility: "public" | "private";
  moderation_status: string;
  created_at: string;
  updated_at: string;
  followers: number;
};
type ReactionResponse = {
  items: Reaction[];
  counts: { all: number; public: number; private: number };
  page: number;
  page_size: number;
};
type Follows = {
  users: { username: string; display_name: string; avatar_path: string | null }[];
  chemicals: { id: number; preferred_name: string | null; iupac_name: string | null }[];
  reactions: { id: number; reaction_smiles: string }[];
  counts: { users: number; chemicals: number; reactions: number };
};
type Notice = {
  id: number;
  event_type: "new_reaction" | "reaction_updated";
  reaction_id: number;
  actor_display_name: string | null;
  created_at: string;
  read_at: string | null;
};
type LoadState = "loading" | "ready" | "error";
type Tab = "overview" | "public" | "private" | "following" | "activity";

const tabs: { id: Tab; label: string }[] = [
  { id: "overview", label: "概览" },
  { id: "public", label: "公开反应" },
  { id: "private", label: "私有反应" },
  { id: "following", label: "我的关注" },
  { id: "activity", label: "动态" },
];

export function UserDashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [publicReactions, setPublicReactions] = useState<Reaction[]>([]);
  const [privateReactions, setPrivateReactions] = useState<Reaction[]>([]);
  const [reactionCounts, setReactionCounts] = useState({ all: 0, public: 0, private: 0 });
  const [reactionState, setReactionState] = useState<LoadState>("loading");
  const [follows, setFollows] = useState<Follows | null>(null);
  const [followState, setFollowState] = useState<LoadState>("loading");
  const [notices, setNotices] = useState<Notice[]>([]);
  const [noticeState, setNoticeState] = useState<LoadState>("loading");

  useEffect(() => {
    let active = true;
    async function start() {
      try {
        const response = await fetch("/api/users/me", { cache: "no-store" });
        if (!response.ok) { if (active) setAuthReady(true); return; }
        const value = await response.json() as User;
        if (!active) return;
        setUser(value);
        setAuthReady(true);
        void loadRepositories();
        void loadFollows();
        void loadNotifications();
      } catch {
        if (active) setAuthReady(true);
      }
    }
    async function loadRepositories() {
      try {
        const [publicResponse, privateResponse] = await Promise.all([
          fetch("/api/users/me/reactions?visibility=public&page_size=20", { cache: "no-store" }),
          fetch("/api/users/me/reactions?visibility=private&page_size=20", { cache: "no-store" }),
        ]);
        if (!publicResponse.ok || !privateResponse.ok) throw new Error("repository request failed");
        const [publicData, privateData] = await Promise.all([
          publicResponse.json() as Promise<ReactionResponse>,
          privateResponse.json() as Promise<ReactionResponse>,
        ]);
        if (!active) return;
        setPublicReactions(publicData.items);
        setPrivateReactions(privateData.items);
        setReactionCounts(publicData.counts);
        setReactionState("ready");
      } catch {
        if (active) setReactionState("error");
      }
    }
    async function loadFollows() {
      try {
        const response = await fetch("/api/users/me/follows", { cache: "no-store" });
        if (!response.ok) throw new Error("follow request failed");
        const value = await response.json() as Follows;
        if (active) { setFollows(value); setFollowState("ready"); }
      } catch {
        if (active) setFollowState("error");
      }
    }
    async function loadNotifications() {
      try {
        const response = await fetch("/api/users/me/notifications", { cache: "no-store" });
        if (!response.ok) throw new Error("notification request failed");
        const value = await response.json() as Notice[];
        if (!active) return;
        setNotices(value);
        setNoticeState("ready");
        if (value.some((item) => !item.read_at)) {
          void fetch("/api/users/me/notifications/read", { method: "POST" });
        }
      } catch {
        if (active) setNoticeState("error");
      }
    }
    void start();
    return () => { active = false; };
  }, []);

  const recent = useMemo(
    () => [...publicReactions, ...privateReactions].sort((a, b) => b.id - a.id).slice(0, 4),
    [publicReactions, privateReactions],
  );
  const unread = notices.filter((item) => !item.read_at).length;
  const followed = follows ? follows.counts.users + follows.counts.chemicals + follows.counts.reactions : 0;

  if (authReady && !user) return (
    <div className="auth-required">
      <div><strong>请先登录</strong><span>登录后管理自己的反应与关注。</span></div>
      <Link href="/login">登录或注册</Link>
    </div>
  );
  if (!user) return <p className="context-loading">正在读取账号…</p>;

  return <>
    <header className="dashboard-header">
      <div className="profile-avatar">{user.avatar_url ? <img src={user.avatar_url} alt="" /> : user.display_name.slice(0, 1)}</div>
      <div className="dashboard-identity">
        <span>@{user.username}</span>
        <h1>{user.display_name}</h1>
        <div className="profile-actions">
          <Link className="button primary" href="/submit">＋ 发布新反应</Link>
          <Link className="button secondary" href="/me/settings">账号设置</Link>
          <Link className="text-button" href={`/user/${encodeURIComponent(user.username)}`}>查看公开主页</Link>
        </div>
      </div>
    </header>

    <div className="dashboard-shell">
      <nav className="dashboard-nav" aria-label="用户主页">
        <div className="dashboard-nav-title"><strong>我的化工社</strong><span>反应与关注</span></div>
        {tabs.map((item) => <button type="button" className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)} key={item.id}>
          <span>{item.label}</span>
          {item.id === "public" && <em>{reactionState === "ready" ? reactionCounts.public : "—"}</em>}
          {item.id === "private" && <em>{reactionState === "ready" ? reactionCounts.private : "—"}</em>}
          {item.id === "following" && <em>{followState === "ready" ? followed : "—"}</em>}
          {item.id === "activity" && unread > 0 && <em className="unread-count">{unread}</em>}
        </button>)}
      </nav>

      <main className="dashboard-panel">
        {tab === "overview" && <Overview
          reactions={recent} reactionCounts={reactionCounts} reactionState={reactionState}
          followed={followed} followState={followState} notices={notices} noticeState={noticeState}
          onOpen={setTab}
        />}
        {tab === "public" && <Repository
          title="公开反应" subtitle="任何人都可以查看与关注" items={publicReactions}
          count={reactionCounts.public} state={reactionState} empty="还没有公开反应。"
        />}
        {tab === "private" && <Repository
          title="私有反应" subtitle="仅当前账号可见" items={privateReactions}
          count={reactionCounts.private} state={reactionState} empty="还没有私有反应。"
        />}
        {tab === "following" && <Following follows={follows} state={followState} />}
        {tab === "activity" && <Activity notices={notices} state={noticeState} />}
      </main>
    </div>
  </>;
}

function Overview({ reactions, reactionCounts, reactionState, followed, followState, notices, noticeState, onOpen }: {
  reactions: Reaction[];
  reactionCounts: { all: number; public: number; private: number };
  reactionState: LoadState;
  followed: number;
  followState: LoadState;
  notices: Notice[];
  noticeState: LoadState;
  onOpen: (tab: Tab) => void;
}) {
  const unread = notices.filter((item) => !item.read_at).length;
  return <>
    <div className="dashboard-panel-heading"><div><p>OVERVIEW</p><h2>概览</h2></div><Link href="/submit">发布反应</Link></div>
    <div className="dashboard-stats">
      <button onClick={() => onOpen("public")}><strong>{reactionState === "ready" ? reactionCounts.public : "—"}</strong><span>公开反应</span></button>
      <button onClick={() => onOpen("private")}><strong>{reactionState === "ready" ? reactionCounts.private : "—"}</strong><span>私有反应</span></button>
      <button onClick={() => onOpen("following")}><strong>{followState === "ready" ? followed : "—"}</strong><span>全部关注</span></button>
      <button onClick={() => onOpen("activity")}><strong>{noticeState === "ready" ? unread : "—"}</strong><span>未读动态</span></button>
    </div>
    <section className="dashboard-section compact-section">
      <div className="section-heading"><div><p>RECENT</p><h2>最近的反应</h2></div>{reactionCounts.all > reactions.length && <button className="text-button" onClick={() => onOpen("public")}>查看仓库</button>}</div>
      {reactionState === "loading" && <PanelLoading />}
      {reactionState === "error" && <PanelError />}
      {reactionState === "ready" && (reactions.length ? <ReactionCards items={reactions} /> : <DashboardEmpty text="你的反应仓库还是空的。" action />)}
    </section>
    {noticeState === "ready" && notices.some((item) => !item.read_at) && <section className="dashboard-section compact-section">
      <div className="section-heading"><div><p>UPDATES</p><h2>最新动态</h2></div><button className="text-button" onClick={() => onOpen("activity")}>查看全部</button></div>
      <NoticeList items={notices.filter((item) => !item.read_at).slice(0, 4)} />
    </section>}
  </>;
}

function Repository({ title, subtitle, items, count, state, empty }: {
  title: string; subtitle: string; items: Reaction[]; count: number; state: LoadState; empty: string;
}) {
  return <section>
    <div className="dashboard-panel-heading"><div><p>REACTIONS</p><h2>{title}</h2><span>{subtitle}</span></div><strong>{state === "ready" ? count : "—"} 条</strong></div>
    {state === "loading" && <PanelLoading />}
    {state === "error" && <PanelError />}
    {state === "ready" && (items.length ? <ReactionCards items={items} /> : <DashboardEmpty text={empty} action />)}
    {state === "ready" && count > items.length && <p className="result-limit">当前显示最近 {items.length} 条。</p>}
  </section>;
}

function ReactionCards({ items }: { items: Reaction[] }) {
  return <div className="repository-grid">{items.map((item) => <article key={item.id}>
    <header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link><span>{new Date(item.updated_at).toLocaleDateString("zh-CN")}</span></header>
    <Link className="repository-scheme" href={`/reaction/${item.id}`}><img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link>
    <footer><span>{item.visibility === "public" ? `${item.followers} 人关注` : "仅自己可见"}</span><Link href={`/submit?reaction=${item.id}`}>编辑</Link></footer>
  </article>)}</div>;
}

function Following({ follows, state }: { follows: Follows | null; state: LoadState }) {
  return <section>
    <div className="dashboard-panel-heading"><div><p>FOLLOWING</p><h2>我的关注</h2><span>追踪与你有关的用户、化合物和反应。</span></div></div>
    {state === "loading" && <PanelLoading />}
    {state === "error" && <PanelError />}
    {state === "ready" && follows && <div className="following-columns">
      <FollowList title="用户" count={follows.counts.users} items={follows.users.map((item) => ({ href: `/user/${encodeURIComponent(item.username)}`, label: item.display_name }))} />
      <FollowList title="化合物" count={follows.counts.chemicals} items={follows.chemicals.map((item) => ({ href: `/chemical/${item.id}`, label: item.preferred_name || item.iupac_name || `HCID ${item.id}` }))} />
      <FollowList title="反应" count={follows.counts.reactions} items={follows.reactions.map((item) => ({ href: `/reaction/${item.id}`, label: `HRID ${item.id}` }))} />
    </div>}
  </section>;
}

function Activity({ notices, state }: { notices: Notice[]; state: LoadState }) {
  return <section>
    <div className="dashboard-panel-heading"><div><p>ACTIVITY</p><h2>关注动态</h2><span>你关注的公开反应及其更新。</span></div></div>
    {state === "loading" && <PanelLoading />}
    {state === "error" && <PanelError />}
    {state === "ready" && (notices.length ? <NoticeList items={notices} /> : <DashboardEmpty text="暂时没有关注动态。" />)}
  </section>;
}

function NoticeList({ items }: { items: Notice[] }) {
  return <div className="notification-list">{items.map((item) => <Link href={`/reaction/${item.reaction_id}`} key={item.id}>
    <span><strong>{item.event_type === "new_reaction" ? `${item.actor_display_name || "关注用户"} 发布了新反应` : "关注的反应已更新"}</strong><small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></span>
    <EntityId kind="reaction" id={item.reaction_id} compact />
  </Link>)}</div>;
}

function FollowList({ title, count, items }: { title: string; count: number; items: { href: string; label: string }[] }) {
  return <div><h3>{title}<span>{count}</span></h3>{items.length ? items.slice(0, 20).map((item) => <Link href={item.href} key={item.href}>{item.label}</Link>) : <p>暂无关注</p>}</div>;
}

function DashboardEmpty({ text, action = false }: { text: string; action?: boolean }) {
  return <div className="dashboard-empty"><p>{text}</p>{action && <Link className="button secondary small" href="/submit">发布第一条反应</Link>}</div>;
}

function PanelLoading() { return <p className="panel-state">正在读取…</p>; }
function PanelError() { return <p className="panel-state error">数据读取失败，请刷新后重试。</p>; }
