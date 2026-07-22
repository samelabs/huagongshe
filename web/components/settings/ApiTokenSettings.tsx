"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

type Token = { id: number; name: string; token_prefix: string; created_at: string; expires_at: string | null; last_used_at: string | null; revoked_at: string | null };
type CreatedToken = { agent_connection_text: string };

export function ApiTokenSettings() {
  const { user, ready } = useAccount();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState("");

  async function loadTokens() {
    const response = await fetch("/api/users/me/tokens", { cache: "no-store" });
    if (response.ok) setTokens(await response.json());
  }
  async function copyConnection() {
    if (!createdToken) return;
    try {
      await navigator.clipboard.writeText(createdToken.agent_connection_text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setMessage("复制失败，请手动复制。");
    }
  }
  useEffect(() => { if (user) void loadTokens(); }, [user]);

  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后设置 AI 授权。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>AI</span><div><h2>AI 授权</h2><p>允许你的 AI 助手查询、校验并新建反应记录。修改和删除仍需在网页完成。</p></div></div>
    <form className="token-create" onSubmit={async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      setCreatedToken(null);
      setCopied(false);
      setMessage("");
      const values = new FormData(form);
      const response = await fetch("/api/users/me/tokens", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: values.get("name"), expires_in_days: Number(values.get("days")) || null }) });
      const body = await response.json().catch(() => null);
      if (response.ok && body?.token && body?.agent_connection_text) {
        setCreatedToken({ agent_connection_text: body.agent_connection_text });
        form.reset();
        await loadTokens();
      }
      else setMessage(body?.detail || "AI 授权创建失败。");
    }}>
      <input name="name" placeholder="例如：文献整理工具" required maxLength={80} />
      <select name="days" defaultValue="90"><option value="30">30 天</option><option value="90">90 天</option><option value="365">1 年</option><option value="">不设到期时间</option></select>
      <button className="button primary small">创建 AI 授权</button>
    </form>
    {createdToken && <div className="token-secret"><div><strong>AI 授权已创建，仅显示一次</strong><button type="button" className="button primary small" onClick={copyConnection}>{copied ? "已复制" : "复制给 AI"}</button></div><textarea className="token-connection" readOnly value={createdToken.agent_connection_text} aria-label="AI 连接信息" /><span>复制内容已经包含连接入口、操作要求和 Token，不需要再单独配置。离开本页后无法再次查看。</span></div>}
    {message && <p className="form-message bad">{message}</p>}
    <div className="token-list">{tokens.map((token) => {
      const expired = Boolean(token.expires_at && new Date(token.expires_at).getTime() <= Date.now());
      const status = token.revoked_at ? "已撤销" : expired ? "已过期" : "有效";
      const expires = token.expires_at ? `到期：${new Date(token.expires_at).toLocaleDateString("zh-CN")}` : "长期有效";
      return <article key={token.id}><div><strong>{token.name}</strong><span>{token.token_prefix}… · {status}</span><small>{token.last_used_at ? `最近使用：${new Date(token.last_used_at).toLocaleString("zh-CN")}` : "尚未使用"} · {expires}</small></div>{!token.revoked_at && !expired && <button className="text-button" onClick={async () => { await fetch(`/api/users/me/tokens/${token.id}`, { method: "DELETE" }); await loadTokens(); }}>撤销</button>}</article>;
    })}</div>
    <Link className="api-guide-link" href="/guide">查看 AI 授权使用说明</Link>
  </section>;
}
