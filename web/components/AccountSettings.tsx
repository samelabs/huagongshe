"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { User } from "@/lib/api";

type Token = { id: number; name: string; token_prefix: string; created_at: string; expires_at: string | null; last_used_at: string | null; revoked_at: string | null };

export function AccountSettings() {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState({ display_name: "", bio: "" });
  const [tokens, setTokens] = useState<Token[]>([]);
  const [createdToken, setCreatedToken] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    fetch("/api/users/me", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) return;
      const current = await response.json() as User;
      setUser(current);
      const publicResponse = await fetch(`/api/users/${encodeURIComponent(current.username)}`, { cache: "no-store" });
      if (publicResponse.ok) { const value = await publicResponse.json(); setProfile({ display_name: value.display_name, bio: value.bio || "" }); }
    });
    loadTokens();
  }, []);
  async function loadTokens() { const response = await fetch("/api/users/me/tokens", { cache: "no-store" }); if (response.ok) setTokens(await response.json()); }
  if (!user) return <div className="auth-required"><div><strong>请先登录</strong><span>登录后管理账号和 Agent Token。</span></div><Link href="/login">登录</Link></div>;
  return <div className="settings-stack">
    <section className="form-section"><div className="form-section-head"><span>PROFILE</span><div><h2>公开资料</h2><p>头像、展示名称和简介会出现在你的公开主页与反应页面。</p></div></div><form className="form-fields" onSubmit={async (event) => { event.preventDefault(); const response = await fetch("/api/users/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) }); setMessage(response.ok ? "资料已保存。" : "资料保存失败。"); }}><label>展示名称<input value={profile.display_name} onChange={(event) => setProfile((value) => ({ ...value, display_name: event.target.value }))} maxLength={80} required /></label><label>简介<textarea value={profile.bio} onChange={(event) => setProfile((value) => ({ ...value, bio: event.target.value }))} maxLength={500} rows={4} /></label><button className="button primary small">保存资料</button></form></section>
    <section className="form-section"><div className="form-section-head"><span>AVATAR</span><div><h2>头像</h2><p>上传后自动裁切、移除图片元数据并生成压缩 WebP。</p></div></div><form className="avatar-upload" onSubmit={async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const response = await fetch("/api/users/me/avatar", { method: "POST", body: form }); setMessage(response.ok ? "头像已更新。刷新页面后生效。" : "头像上传失败，请检查图片大小和格式。"); }}><input name="image" type="file" accept="image/jpeg,image/png,image/webp" required /><button className="button secondary small">上传头像</button></form></section>
    <section className="form-section"><div className="form-section-head"><span>SECURITY</span><div><h2>修改密码</h2><p>修改后所有网页登录会话和 Agent Token 都会失效。</p></div></div><form className="form-fields" onSubmit={async (event) => { event.preventDefault(); const values = new FormData(event.currentTarget); const response = await fetch("/api/users/me/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: values.get("current_password"), new_password: values.get("new_password"), confirm_password: values.get("confirm_password") }) }); if (response.ok) window.location.href = "/login"; else setMessage("密码修改失败，请核对当前密码和新密码要求。"); }}><label>当前密码<input name="current_password" type="password" required /></label><label>新密码<input name="new_password" type="password" minLength={10} required /></label><label>确认新密码<input name="confirm_password" type="password" minLength={10} required /></label><button className="button secondary small">修改密码</button></form></section>
    <section className="form-section"><div className="form-section-head"><span>AI AGENT</span><div><h2>Agent Token</h2><p>Token 绑定当前账号，用于查询化学数据和发布反应。明文只显示一次。</p></div></div><form className="token-create" onSubmit={async (event) => { event.preventDefault(); setCreatedToken(""); const values = new FormData(event.currentTarget); const response = await fetch("/api/users/me/tokens", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: values.get("name"), expires_in_days: Number(values.get("days")) || null }) }); const body = await response.json().catch(() => null); if (response.ok) { setCreatedToken(body.token); event.currentTarget.reset(); await loadTokens(); } else setMessage(body?.detail || "Token 创建失败。"); }}><input name="name" placeholder="例如：文献整理 Agent" required maxLength={80} /><select name="days" defaultValue="90"><option value="30">30 天</option><option value="90">90 天</option><option value="365">1 年</option><option value="">不设到期时间</option></select><button className="button primary small">创建 Token</button></form>{createdToken && <div className="token-secret"><strong>立即复制，关闭后无法再次查看</strong><code>{createdToken}</code></div>}<div className="token-list">{tokens.map((token) => <article key={token.id}><div><strong>{token.name}</strong><span>{token.token_prefix}… · {token.revoked_at ? "已撤销" : "有效"}</span></div>{!token.revoked_at && <button className="text-button" onClick={async () => { await fetch(`/api/users/me/tokens/${token.id}`, { method: "DELETE" }); await loadTokens(); }}>撤销</button>}</article>)}</div><a className="agent-guide-link" href="/api/agent-guide" target="_blank">查看 Agent 使用规则</a></section>
    {message && <p className="form-message ok">{message}</p>}
  </div>;
}
