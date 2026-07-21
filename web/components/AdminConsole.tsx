"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EntityId } from "@/components/EntityId";

type UserRow = { id: number; username: string; display_name: string; email: string; role: string; status: "active" | "disabled"; created_at: string; count: number };
type ReactionRow = { id: number; reaction_smiles: string; visibility: string; moderation_status: "visible" | "hidden"; username: string; display_name: string; created_at: string };

export function AdminConsole() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [reactions, setReactions] = useState<ReactionRow[]>([]);
  const [error, setError] = useState("");
  async function load() {
    const [userResponse, reactionResponse] = await Promise.all([fetch("/api/admin/users", { cache: "no-store" }), fetch("/api/admin/reactions", { cache: "no-store" })]);
    if (userResponse.status === 403 || userResponse.status === 401) { setError("没有平台管理权限。"); return; }
    if (userResponse.ok) setUsers(await userResponse.json());
    if (reactionResponse.ok) setReactions(await reactionResponse.json());
  }
  useEffect(() => { load(); }, []);
  if (error) return <div className="notice error">{error}</div>;
  return <div className="admin-console">
    <section className="dashboard-section"><div className="section-heading"><div><p>USERS</p><h2>用户管理</h2></div><span>{users.length} 个账号</span></div><div className="admin-table">{users.map((user) => <article key={user.id}><div><strong>{user.display_name}</strong><span>@{user.username} · {user.email}</span></div><span className={`status ${user.status}`}>{user.status === "active" ? "正常" : "已停用"}</span><button className="text-button" onClick={async () => { await fetch(`/api/admin/users/${user.id}/status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: user.status === "active" ? "disabled" : "active" }) }); await load(); }}>{user.status === "active" ? "停用" : "恢复"}</button></article>)}</div></section>
    <section className="dashboard-section"><div className="section-heading"><div><p>VISIBILITY</p><h2>用户反应可见度</h2></div><span>{reactions.length} 条</span></div><div className="admin-table reaction-admin-list">{reactions.map((reaction) => <article key={reaction.id}><div><Link href={`/reaction/${reaction.id}`}><EntityId kind="reaction" id={reaction.id} compact /></Link><span>{reaction.display_name} · {reaction.visibility === "public" ? "公开" : "私有"}</span></div><span className={`status ${reaction.moderation_status}`}>{reaction.moderation_status === "visible" ? "正常展示" : "已隐藏"}</span><button className="text-button" onClick={async () => { await fetch(`/api/admin/reactions/${reaction.id}/moderation`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: reaction.moderation_status === "visible" ? "hidden" : "visible" }) }); await load(); }}>{reaction.moderation_status === "visible" ? "隐藏" : "恢复"}</button></article>)}</div></section>
  </div>;
}
