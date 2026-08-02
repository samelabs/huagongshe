"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import t from "@/lib/i18n";

type Token = { id: number; name: string; token_prefix: string; created_at: string; expires_at: string | null; last_used_at: string | null; revoked_at: string | null };
type CreatedToken = { agent_connection_text: string };

export function ApiTokenSettings() {
  const { user, ready } = useAccount();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  async function loadTokens() {
    try {
      const response = await fetch("/api/users/me/tokens", { cache: "no-store" });
      if (!response.ok) throw new Error();
      setTokens(await response.json());
    } catch {
      setMessage(t.settings.ai.loadFailed);
    }
  }
  async function copyConnection() {
    if (!createdToken) return;
    try {
      await navigator.clipboard.writeText(createdToken.agent_connection_text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setMessage(t.settings.ai.copyFailed);
    }
  }
  useEffect(() => { if (user) void loadTokens(); }, [user]);

  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.ai.loginHint} />;

  return <section className="form-section">
    <div className="form-section-head"><span>{t.settings.ai.title}</span><div><h2>{t.settings.ai.title}</h2><p>{t.settings.ai.desc}</p></div></div>
    <form className="token-create" onSubmit={async (event) => {
      event.preventDefault();
      if (creating) return;
      const form = event.currentTarget;
      setCreatedToken(null);
      setCopied(false);
      setMessage("");
      setCreating(true);
      try {
        const values = new FormData(form);
        const response = await fetch("/api/users/me/tokens", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: values.get("name"), expires_in_days: Number(values.get("days")) || null }) });
        const body = await response.json().catch(() => null);
        if (!response.ok || !body?.token || !body?.agent_connection_text) {
          setMessage(apiError(body?.detail, t.settings.ai.createFailed));
          return;
        }
        setCreatedToken({ agent_connection_text: body.agent_connection_text });
        form.reset();
        await loadTokens();
      } catch {
        setMessage(t.common.networkError);
      } finally { setCreating(false); }
    }}>
      <input name="name" placeholder={t.settings.ai.placeholder} required maxLength={80} disabled={creating} />
      <select name="days" defaultValue="90" disabled={creating}><option value="30">{t.settings.ai.days30}</option><option value="90">{t.settings.ai.days90}</option><option value="365">{t.settings.ai.days365}</option><option value="">{t.settings.ai.noExpiry}</option></select>
      <button type="submit" className="button primary small" disabled={creating}>{creating ? t.settings.ai.creating : t.settings.ai.createBtn}</button>
    </form>
    {createdToken && <div className="token-secret"><div><strong>{t.settings.ai.created}</strong><button type="button" className="button primary small" onClick={copyConnection}>{copied ? t.settings.ai.copied : t.settings.ai.copyToAI}</button></div><textarea className="token-connection" readOnly value={createdToken.agent_connection_text} aria-label={t.settings.ai.connectionLabel} /><span>{t.settings.ai.copyHint}</span></div>}
    {message && <p className="form-message bad">{message}</p>}
    <div className="token-list">{tokens.map((token) => {
      const expired = Boolean(token.expires_at && new Date(token.expires_at).getTime() <= Date.now());
      const status = token.revoked_at ? t.settings.ai.statusRevoked : expired ? t.settings.ai.statusExpired : t.settings.ai.statusValid;
      const expires = token.expires_at ? t.settings.ai.expiresAt(new Date(token.expires_at).toLocaleDateString("zh-CN")) : t.settings.ai.longTerm;
      return <article key={token.id}><div><strong>{token.name}</strong><span>{token.token_prefix}… · {status}</span><small>{token.last_used_at ? t.settings.ai.lastUsed(new Date(token.last_used_at).toLocaleString("zh-CN")) : t.settings.ai.neverUsed} · {expires}</small></div>{!token.revoked_at && !expired && <button type="button" className="text-button" disabled={revokingId !== null} onClick={async () => {
        setRevokingId(token.id); setMessage("");
        try {
          const response = await fetch(`/api/users/me/tokens/${token.id}`, { method: "DELETE" });
          if (!response.ok) throw new Error();
          await loadTokens();
        } catch { setMessage(t.settings.ai.revokeFailed); }
        finally { setRevokingId(null); }
      }}>{revokingId === token.id ? t.settings.ai.revoking : t.settings.ai.revoke}</button>}</article>;
    })}</div>
    <Link className="api-guide-link" href="/guide">{t.settings.ai.guideLink}</Link>
  </section>;
}

function apiError(detail: unknown, fallback: string) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg).filter(Boolean).join("；") || fallback;
  return fallback;
}
