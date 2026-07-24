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
  const [busyId, setBusyId] = useState<number | null>(null);
  async function load() {
    const [userResponse, reactionResponse] = await Promise.all([fetch("/api/admin/users", { cache: "no-store" }), fetch("/api/admin/reactions", { cache: "no-store" })]);
    if (userResponse.status === 403 || userResponse.status === 401) { setError("没有平台管理权限。"); return; }
    if (userResponse.ok) setUsers(await userResponse.json());
    if (reactionResponse.ok) setReactions(await reactionResponse.json());
  }
  useEffect(() => { load(); }, []);
  async function patch(url: string, id: number, body: Record<string, unknown>) {
    setError("");
    setBusyId(id);
    try {
      const response = await fetch(url, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error();
      await load();
    } catch {
      setError("操作失败，请稍后重试。");
    } finally {
      setBusyId(null);
    }
  }
  if (error && !users.length) return <div className="notice error">{error}</div>;
  return <div className="admin-console">
    {error && users.length > 0 && <div className="notice error">{error}</div>}
    <section className="dashboard-section"><div className="section-heading"><div><p>USERS</p><h2>用户管理</h2></div><span>{users.length} 个账号</span></div><div className="admin-table">{users.map((user) => <article key={user.id}><div><strong>{user.display_name}</strong><span>@{user.username} · {user.email}</span></div><span className={`status ${user.status}`}>{user.status === "active" ? "正常" : "已停用"}</span><button className="text-button" disabled={busyId === user.id} onClick={() => patch(`/api/admin/users/${user.id}/status`, user.id, { status: user.status === "active" ? "disabled" : "active" })}>{busyId === user.id ? "…" : user.status === "active" ? "停用" : "恢复"}</button></article>)}</div></section>
    <section className="dashboard-section"><div className="section-heading"><div><p>VISIBILITY</p><h2>用户反应可见度</h2></div><span>{reactions.length} 条</span></div><div className="admin-table reaction-admin-list">{reactions.map((reaction) => <article key={reaction.id}><div><Link href={`/reaction/${reaction.id}`}><EntityId kind="reaction" id={reaction.id} compact /></Link><span>{reaction.display_name} · {reaction.visibility === "public" ? "公开" : "私有"}</span></div><span className={`status ${reaction.moderation_status}`}>{reaction.moderation_status === "visible" ? "正常展示" : "已隐藏"}</span><button className="text-button" disabled={busyId === reaction.id} onClick={() => patch(`/api/admin/reactions/${reaction.id}/moderation`, reaction.id, { status: reaction.moderation_status === "visible" ? "hidden" : "visible" })}>{busyId === reaction.id ? "…" : reaction.moderation_status === "visible" ? "隐藏" : "恢复"}</button></article>)}</div></section>
  </div>;
}
