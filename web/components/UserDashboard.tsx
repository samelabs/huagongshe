"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EntityId } from "@/components/EntityId";
import { reactionSvgUrl, type User } from "@/lib/api";

type Reaction = { id: number; reaction_smiles: string; visibility: "public" | "private"; moderation_status: string; created_at: string; updated_at: string; followers: number };
type Follows = {
  users: { username: string; display_name: string; avatar_path: string | null }[];
  chemicals: { id: number; preferred_name: string | null; iupac_name: string | null }[];
  reactions: { id: number; reaction_smiles: string }[];
};
type Notice = { id: number; event_type: string; reaction_id: number; actor_display_name: string | null; created_at: string; read_at: string | null };

export function UserDashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [reactions, setReactions] = useState<Reaction[]>([]);
  const [follows, setFollows] = useState<Follows | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    Promise.all([
      fetch("/api/users/me", { cache: "no-store" }),
      fetch("/api/users/me/reactions", { cache: "no-store" }),
      fetch("/api/users/me/follows", { cache: "no-store" }),
      fetch("/api/users/me/notifications", { cache: "no-store" }),
    ]).then(async ([me, reactionResponse, followResponse, noticeResponse]) => {
      if (!me.ok) { setReady(true); return; }
      setUser(await me.json());
      if (reactionResponse.ok) setReactions(await reactionResponse.json());
      if (followResponse.ok) setFollows(await followResponse.json());
      if (noticeResponse.ok) {
        const values = await noticeResponse.json(); setNotices(values);
        if (values.some((item: Notice) => !item.read_at)) fetch("/api/users/me/notifications/read", { method: "POST" });
      }
      setReady(true);
    }).catch(() => setReady(true));
  }, []);
  if (ready && !user) return <div className="auth-required"><div><strong>请先登录</strong><span>登录后管理你的反应仓库和关注。</span></div><Link href="/login">登录或注册</Link></div>;
  if (!user) return <p className="context-loading">正在读取反应仓库…</p>;
  const publicItems = reactions.filter((item) => item.visibility === "public");
  const privateItems = reactions.filter((item) => item.visibility === "private");
  return <>
    <header className="profile-header">
      <div className="profile-avatar">{user.avatar_url ? <img src={user.avatar_url} alt="" /> : user.display_name.slice(0, 1)}</div>
      <div><p>@{user.username}</p><h1>{user.display_name}</h1><div className="profile-actions"><Link className="button primary small" href="/submit">发布反应</Link><Link className="button secondary small" href="/me/settings">账号与 Agent</Link><Link className="text-button" href={`/user/${user.username}`}>查看公开主页</Link></div></div>
    </header>
    {notices.some((item) => !item.read_at) && <section className="dashboard-section"><div className="section-heading compact-heading"><div><p>UPDATES</p><h2>关注动态</h2></div></div><div className="notification-list">{notices.filter((item) => !item.read_at).slice(0, 8).map((item) => <Link href={`/reaction/${item.reaction_id}`} key={item.id}>{item.event_type === "new_reaction" ? `${item.actor_display_name || "关注用户"} 发布了新反应` : "关注的反应已更新"}<EntityId kind="reaction" id={item.reaction_id} compact /></Link>)}</div></section>}
    <Repository title="公开仓库" subtitle="可被查询和关注" items={publicItems} />
    <Repository title="私有仓库" subtitle="仅自己可见" items={privateItems} />
    <section className="dashboard-section"><div className="section-heading compact-heading"><div><p>FOLLOWING</p><h2>我的关注</h2></div></div>{follows && <div className="following-columns">
      <FollowList title="用户" items={follows.users.map((item) => ({ href: `/user/${item.username}`, label: item.display_name }))} />
      <FollowList title="化合物" items={follows.chemicals.map((item) => ({ href: `/chemical/${item.id}`, label: item.preferred_name || item.iupac_name || `HCID ${item.id}` }))} />
      <FollowList title="反应" items={follows.reactions.map((item) => ({ href: `/reaction/${item.id}`, label: `HRID ${item.id}` }))} />
    </div>}</section>
  </>;
}

function Repository({ title, subtitle, items }: { title: string; subtitle: string; items: Reaction[] }) {
  return <section className="dashboard-section"><div className="section-heading compact-heading"><div><p>REACTIONS</p><h2>{title}</h2></div><span>{items.length} 条 · {subtitle}</span></div>{items.length ? <div className="repository-grid">{items.map((item) => <article key={item.id}><header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link><span>{new Date(item.updated_at).toLocaleDateString("zh-CN")}</span></header><Link className="repository-scheme" href={`/reaction/${item.id}`}><img src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link><footer><span>{item.visibility === "public" ? `${item.followers} 人关注` : "仅自己可见"}</span><Link href={`/submit?reaction=${item.id}`}>编辑</Link></footer></article>)}</div> : <p className="quiet-empty">这里还没有反应。</p>}</section>;
}

function FollowList({ title, items }: { title: string; items: { href: string; label: string }[] }) {
  return <div><h3>{title}<span>{items.length}</span></h3>{items.length ? items.slice(0, 20).map((item) => <Link href={item.href} key={item.href}>{item.label}</Link>) : <p>暂无关注</p>}</div>;
}
