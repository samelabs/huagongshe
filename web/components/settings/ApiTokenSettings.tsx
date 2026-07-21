"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

type Token = { id: number; name: string; token_prefix: string; created_at: string; expires_at: string | null; last_used_at: string | null; revoked_at: string | null };

export function ApiTokenSettings() {
  const { user, ready } = useAccount();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [createdToken, setCreatedToken] = useState("");
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState("");

  async function loadTokens() {
    const response = await fetch("/api/users/me/tokens", { cache: "no-store" });
    if (response.ok) setTokens(await response.json());
  }
  async function copyToken() {
    try {
      await navigator.clipboard.writeText(createdToken);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setMessage("复制失败，请手动复制 Token。");
    }
  }
  useEffect(() => { if (user) void loadTokens(); }, [user]);

  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后管理 API Token。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>API</span><div><h2>API Token</h2><p>用于授权 AI 查询、校验和提交反应。Token 仅显示一次。</p></div></div>
    <form className="token-create" onSubmit={async (event) => {
      event.preventDefault();
      setCreatedToken("");
      setCopied(false);
      setMessage("");
      const values = new FormData(event.currentTarget);
      const response = await fetch("/api/users/me/tokens", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: values.get("name"), expires_in_days: Number(values.get("days")) || null }) });
      const body = await response.json().catch(() => null);
      if (response.ok) { setCreatedToken(body.token); event.currentTarget.reset(); await loadTokens(); }
      else setMessage(body?.detail || "API Token 创建失败。");
    }}>
      <input name="name" placeholder="例如：文献整理工具" required maxLength={80} />
      <select name="days" defaultValue="90"><option value="30">30 天</option><option value="90">90 天</option><option value="365">1 年</option><option value="">不设到期时间</option></select>
      <button className="button primary small">创建 API Token</button>
    </form>
    {createdToken && <div className="token-secret"><div><strong>请立即保存</strong><button type="button" className="button secondary small" onClick={copyToken}>{copied ? "已复制" : "复制 Token"}</button></div><code>{createdToken}</code><span>离开本页后无法再次查看。</span></div>}
    {message && <p className="form-message bad">{message}</p>}
    <div className="token-list">{tokens.map((token) => <article key={token.id}><div><strong>{token.name}</strong><span>{token.token_prefix}… · {token.revoked_at ? "已撤销" : "有效"}</span><small>{token.last_used_at ? `最近使用：${new Date(token.last_used_at).toLocaleString("zh-CN")}` : "尚未使用"}</small></div>{!token.revoked_at && <button className="text-button" onClick={async () => { await fetch(`/api/users/me/tokens/${token.id}`, { method: "DELETE" }); await loadTokens(); }}>撤销</button>}</article>)}</div>
    <Link className="api-guide-link" href="/guide">查看 AI 与 API 使用指南</Link>
  </section>;
}
