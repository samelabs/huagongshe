"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { EntityId } from "@/components/EntityId";
import { PersonList, type PersonSummary } from "@/components/PersonList";
import { reactionSvgUrl } from "@/lib/api";

type LoadState = "loading" | "ready" | "error";
export type DashboardTab = "public" | "private" | "people" | "followers" | "chemicals" | "reactions" | "activity";
type Counts = { public_reactions: number; private_reactions: number; following: number; followers: number; chemicals: number; reactions: number; unread: number };
type Summary = { username: string; display_name: string; bio: string | null; avatar_url: string | null; counts: Counts };
type Reaction = { id: number; reaction_smiles: string; visibility?: "public" | "private"; updated_at?: string; followers?: number };
type ReactionResponse = { items: Reaction[]; counts: { all: number; public: number; private: number }; page: number; page_size: number };
type PeopleResponse = { items: PersonSummary[]; total: number; page: number; page_size: number };
type ChemicalFollow = { id: number; preferred_name: string | null; iupac_name: string | null; smiles: string | null };
type PageResponse<T> = { items: T[]; total: number; page: number; page_size: number };
type Notice = { id: number; event_type: "new_reaction" | "reaction_updated"; reaction_id: number; actor_display_name: string | null; created_at: string; read_at: string | null };

const tabs: { id: DashboardTab; label: string }[] = [
  { id: "public", label: "公开反应" },
  { id: "private", label: "私有反应" },
  { id: "people", label: "关注的人" },
  { id: "followers", label: "粉丝" },
  { id: "chemicals", label: "关注的化合物" },
  { id: "reactions", label: "关注的反应" },
  { id: "activity", label: "动态" },
];
const emptyPage = <T,>(): PageResponse<T> => ({ items: [], total: 0, page: 1, page_size: 40 });

export function UserDashboard({ activeTab, page }: { activeTab: DashboardTab; page: number }) {
  const { user, ready: authReady } = useAccount();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryState, setSummaryState] = useState<LoadState>("loading");
  const [contentState, setContentState] = useState<LoadState>("loading");
  const [reactions, setReactions] = useState<Reaction[]>([]);
  const [people, setPeople] = useState<PeopleResponse>(emptyPage<PersonSummary>());
  const [chemicals, setChemicals] = useState<PageResponse<ChemicalFollow>>(emptyPage<ChemicalFollow>());
  const [followedReactions, setFollowedReactions] = useState<PageResponse<Reaction>>(emptyPage<Reaction>());
  const [notices, setNotices] = useState<Notice[]>([]);

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
    let active = true;
    const username = encodeURIComponent(user.username);
    setContentState("loading");
    async function load() {
      let response: Response;
      if (activeTab === "public" || activeTab === "private") {
        response = await fetch(`/api/users/me/reactions?visibility=${activeTab}&page=${page}&page_size=20`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as ReactionResponse;
        if (active) setReactions(value.items);
      } else if (activeTab === "people" || activeTab === "followers") {
        const relation = activeTab === "people" ? "following" : "followers";
        response = await fetch(`/api/users/${username}/${relation}?page=${page}&page_size=40`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as PeopleResponse;
        if (active) setPeople(value);
      } else if (activeTab === "chemicals") {
        response = await fetch(`/api/users/me/follows/chemicals?page=${page}&page_size=40`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as PageResponse<ChemicalFollow>;
        if (active) setChemicals(value);
      } else if (activeTab === "reactions") {
        response = await fetch(`/api/users/me/follows/reactions?page=${page}&page_size=20`, { cache: "no-store" });
        if (!response.ok) throw new Error();
        const value = await response.json() as PageResponse<Reaction>;
        if (active) setFollowedReactions(value);
      } else {
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
      }
      if (active) setContentState("ready");
    }
    void load().catch(() => { if (active) setContentState("error"); });
    return () => { active = false; };
  }, [activeTab, page, user]);

  if (authReady && !user) return <div className="auth-required"><div><strong>请先登录</strong><span>登录后管理自己的反应与关注。</span></div><Link href="/login">登录或注册</Link></div>;
  if (!user) return <p className="context-loading">正在读取账号…</p>;

  const profile = summary || user;
  const counts = summary?.counts;
  const countFor = (tab: DashboardTab) => {
    if (!counts) return "—";
    return ({ public: counts.public_reactions, private: counts.private_reactions, people: counts.following, followers: counts.followers, chemicals: counts.chemicals, reactions: counts.reactions, activity: counts.unread } as Record<DashboardTab, number>)[tab];
  };

  return <>
    <header className="dashboard-header social-profile-header">
      <div className="profile-avatar">{profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : profile.display_name.slice(0, 1)}</div>
      <div className="dashboard-identity"><span>@{profile.username}</span><h1>{profile.display_name}</h1>
        {summary?.bio && <p className="profile-bio">{summary.bio}</p>}
        <div className="profile-counts profile-count-links">
          <Link href="/me"><strong>{countFor("public")}</strong><span>公开反应</span></Link>
          <Link href="/me?tab=people"><strong>{countFor("people")}</strong><span>关注</span></Link>
          <Link href="/me?tab=followers"><strong>{countFor("followers")}</strong><span>粉丝</span></Link>
        </div>
      </div>
      <div className="profile-actions dashboard-profile-actions"><Link className="button secondary" href="/me/settings/profile">编辑资料</Link><Link className="text-button" href={`/user/${encodeURIComponent(user.username)}`}>查看公开主页</Link></div>
    </header>

    <div className="dashboard-shell social-dashboard-shell">
      <nav className="dashboard-nav profile-tabs" aria-label="个人主页内容">{tabs.map((item) => <Link href={item.id === "public" ? "/me" : `/me?tab=${item.id}`} className={activeTab === item.id ? "active" : ""} key={item.id}>
        <span>{item.label}</span><em className={item.id === "activity" && counts?.unread ? "unread-count" : ""}>{item.id === "activity" && countFor(item.id) === 0 ? "" : countFor(item.id)}</em>
      </Link>)}</nav>

      <main className="dashboard-panel">
        {summaryState === "error" && <p className="profile-summary-error">主页统计暂时无法读取。</p>}
        {(activeTab === "public" || activeTab === "private") && <Repository title={activeTab === "public" ? "公开反应" : "私有反应"} subtitle={activeTab === "public" ? "公开主页中的反应条目" : "仅当前账号可见"} items={reactions} count={activeTab === "public" ? counts?.public_reactions : counts?.private_reactions} state={contentState} visibility={activeTab} page={page} />}
        {(activeTab === "people" || activeTab === "followers") && <PeopleSection title={activeTab === "people" ? "关注的人" : "粉丝"} data={people} state={contentState} empty={activeTab === "people" ? "还没有关注用户。" : "还没有粉丝。"} tab={activeTab} />}
        {activeTab === "chemicals" && <ChemicalFollows data={chemicals} state={contentState} />}
        {activeTab === "reactions" && <ReactionFollows data={followedReactions} state={contentState} />}
        {activeTab === "activity" && <Activity notices={notices} state={contentState} />}
      </main>
    </div>
  </>;
}

function Repository({ title, subtitle, items, count, state, visibility, page }: { title: string; subtitle: string; items: Reaction[]; count?: number; state: LoadState; visibility: "public" | "private"; page: number }) {
  const total = count ?? 0;
  return <section><PanelHeading title={title} subtitle={subtitle} count={count ?? "—"} unit="条" />
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}
    {state === "ready" && (items.length ? <ReactionCards items={items} editable /> : <DashboardEmpty text={`还没有${title}。`} action />)}
    {state === "ready" && total > 20 && <Pagination page={page} pageSize={20} total={total} href={(value) => visibility === "public" && value === 1 ? "/me" : `/me?tab=${visibility}&page=${value}`} />}
  </section>;
}

function PeopleSection({ title, data, state, empty, tab }: { title: string; data: PeopleResponse; state: LoadState; empty: string; tab: "people" | "followers" }) {
  return <section><PanelHeading title={title} count={state === "ready" ? data.total : "—"} unit="人" />
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}{state === "ready" && <PersonList items={data.items} empty={empty} />}
    {state === "ready" && data.total > data.page_size && <Pagination page={data.page} pageSize={data.page_size} total={data.total} href={(value) => `/me?tab=${tab}&page=${value}`} />}
  </section>;
}

function ChemicalFollows({ data, state }: { data: PageResponse<ChemicalFollow>; state: LoadState }) {
  return <section><PanelHeading title="关注的化合物" count={state === "ready" ? data.total : "—"} unit="个" />
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}
    {state === "ready" && (data.items.length ? <div className="followed-entity-list">{data.items.map((item) => <Link href={`/chemical/${item.id}`} key={item.id}><EntityId kind="chemical" id={item.id} compact /><span><strong>{item.preferred_name || item.iupac_name || "未命名化合物"}</strong>{item.smiles && <small>{item.smiles}</small>}</span><em>查看</em></Link>)}</div> : <DashboardEmpty text="还没有关注化合物。" />)}
    {state === "ready" && data.total > data.page_size && <Pagination page={data.page} pageSize={data.page_size} total={data.total} href={(value) => `/me?tab=chemicals&page=${value}`} />}
  </section>;
}

function ReactionFollows({ data, state }: { data: PageResponse<Reaction>; state: LoadState }) {
  return <section><PanelHeading title="关注的反应" count={state === "ready" ? data.total : "—"} unit="条" />
    {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}{state === "ready" && (data.items.length ? <ReactionCards items={data.items} /> : <DashboardEmpty text="还没有关注反应。" />)}
    {state === "ready" && data.total > data.page_size && <Pagination page={data.page} pageSize={data.page_size} total={data.total} href={(value) => `/me?tab=reactions&page=${value}`} />}
  </section>;
}

function ReactionCards({ items, editable = false }: { items: Reaction[]; editable?: boolean }) { return <div className="repository-grid">{items.map((item) => <article key={item.id}>
  <header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link>{item.updated_at && <span>{new Date(item.updated_at).toLocaleDateString("zh-CN")}</span>}</header>
  <Link className="repository-scheme" href={`/reaction/${item.id}`}><img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link>
  <footer><span>{item.visibility === "private" ? "仅自己可见" : editable ? `${item.followers || 0} 人关注` : "公开反应"}</span>{editable ? <Link href={`/submit?reaction=${item.id}`}>编辑</Link> : <Link href={`/reaction/${item.id}`}>查看</Link>}</footer>
</article>)}</div>; }

function Activity({ notices, state }: { notices: Notice[]; state: LoadState }) { return <section><PanelHeading title="动态" subtitle="关注用户发布反应或关注反应更新时显示在这里" />
  {state === "loading" && <PanelLoading />}{state === "error" && <PanelError />}{state === "ready" && (notices.length ? <div className="notification-list">{notices.map((item) => <Link href={`/reaction/${item.reaction_id}`} key={item.id}><span><strong>{item.event_type === "new_reaction" ? `${item.actor_display_name || "关注用户"} 发布了新反应` : "关注的反应已更新"}</strong><small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></span><EntityId kind="reaction" id={item.reaction_id} compact /></Link>)}</div> : <DashboardEmpty text="暂时没有动态。" />)}
</section>; }

function PanelHeading({ title, subtitle, count, unit = "" }: { title: string; subtitle?: string; count?: number | string; unit?: string }) { return <div className="dashboard-panel-heading"><div><h2>{title}</h2>{subtitle && <span>{subtitle}</span>}</div>{count !== undefined && <strong>{count} {unit}</strong>}</div>; }
function Pagination({ page, pageSize, total, href }: { page: number; pageSize: number; total: number; href: (page: number) => string }) { const pages = Math.ceil(total / pageSize); return <nav className="profile-pagination" aria-label="分页">{page > 1 ? <Link href={href(page - 1)}>上一页</Link> : <span />}<small>{page} / {pages}</small>{page < pages ? <Link href={href(page + 1)}>下一页</Link> : <span />}</nav>; }
function DashboardEmpty({ text, action = false }: { text: string; action?: boolean }) { return <div className="dashboard-empty"><p>{text}</p>{action && <Link className="button secondary small" href="/submit">发布反应</Link>}</div>; }
function PanelLoading() { return <p className="panel-state">正在读取…</p>; }
function PanelError() { return <p className="panel-state error">数据读取失败，请刷新后重试。</p>; }
