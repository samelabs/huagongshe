"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPost, apiDelete, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type Token = { id: number; name: string; token_prefix: string; token_plain: string | null; created_at: string; expires_at: string | null; last_used_at: string | null };
type CreatedToken = { token: string };

export function ApiTokenSettings() {
  const { user, ready } = useAccount();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [copiedToken, setCopiedToken] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiGet<Token[]>(`/users/me/tokens`).then((data) => {
      if (active) setTokens(data);
    }).catch(() => { if (active) setMessage(t.settings.ai.loadFailed); });
    return () => { active = false; };
  }, [user]);

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
        const body = await apiPost<{ token?: string; detail?: unknown }>(
          `/users/me/tokens`,
          JSON.stringify({ name: values.get("name"), expires_in_days: Number(values.get("days")) || null })
        );
        if (!body?.token) {
          setMessage(t.settings.ai.createFailed);
          return;
        }
        setCreatedToken({ token: body.token });
        form.reset();
        await loadTokens(tokens, setTokens, setMessage);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) setMessage(t.settings.ai.limitReached);
        else if (error instanceof ApiError && error.status === 401) setMessage(t.settings.ai.relogin);
        else if (error instanceof ApiError && error.status === 502) setMessage(t.settings.ai.upstreamDown);
        else setMessage(t.common.networkError);
      } finally { setCreating(false); }
    }}>
      <input name="name" placeholder={t.settings.ai.placeholder} required maxLength={80} disabled={creating} />
      <select name="days" defaultValue="90" disabled={creating}><option value="30">{t.settings.ai.days30}</option><option value="90">{t.settings.ai.days90}</option><option value="365">{t.settings.ai.days365}</option><option value="">{t.settings.ai.noExpiry}</option></select>
      <button type="submit" className="button primary small" disabled={creating}>{creating ? t.settings.ai.creating : t.settings.ai.createBtn}</button>
    </form>
    {createdToken && <div className="token-secret"><div><strong>{t.settings.ai.created}</strong><button type="button" className="button primary small" onClick={async () => {
      try { await navigator.clipboard.writeText(createdToken.token); setCopied(true); window.setTimeout(() => setCopied(false), 1800); } catch { setMessage(t.settings.ai.copyFailed); }
    }}>{copied ? t.settings.ai.copied : t.settings.ai.copyToken}</button></div><code className="token-value">{createdToken.token}</code><span>{t.settings.ai.copyHint}</span></div>}
    {message && <p className="form-message bad">{message}</p>}
    <div className="token-list">{tokens.map((token) => {
      const expired = Boolean(token.expires_at && new Date(token.expires_at).getTime() <= Date.now());
      const status = expired ? t.settings.ai.statusExpired : t.settings.ai.statusValid;
      const expires = token.expires_at ? t.settings.ai.expiresAt(new Date(token.expires_at).toLocaleDateString("zh-CN")) : t.settings.ai.longTerm;
      return <article key={token.id}><div><strong>{token.name}</strong><span>{token.token_prefix}… · {status}</span><small>{token.last_used_at ? t.settings.ai.lastUsed(new Date(token.last_used_at).toLocaleString("zh-CN")) : t.settings.ai.neverUsed} · {expires}</small></div><div className="token-actions">
        {token.token_plain && <button type="button" className="text-button" onClick={async () => {
          try { await navigator.clipboard.writeText(token.token_plain || ""); setCopiedToken(token.id); window.setTimeout(() => setCopiedToken(null), 1800); } catch { setMessage(t.settings.ai.copyFailed); }
        }}>{copiedToken === token.id ? t.settings.ai.copiedShort : t.settings.ai.copyToken}</button>}
        <button type="button" className="text-button" disabled={revokingId !== null} onClick={async () => {
          setRevokingId(token.id); setMessage("");
          try {
            await apiDelete(`/users/me/tokens/${token.id}`);
            await loadTokens(tokens, setTokens, setMessage);
          } catch { setMessage(t.settings.ai.revokeFailed); }
          finally { setRevokingId(null); }
        }}>{revokingId === token.id ? t.settings.ai.revoking : t.settings.ai.revoke}</button>
      </div></article>;
    })}</div>
    <div className="token-help-links">
      <Link className="api-guide-link" href="/guide">{t.settings.ai.guideLink}</Link>
      <Link className="api-guide-link" href="/mcp-guide">{t.settings.ai.mcpGuideLink}</Link>
    </div>
  </section>;
}

async function loadTokens(
  _tokens: Token[],
  setTokens: (ts: Token[]) => void,
  setMessage: (m: string) => void,
) {
  try {
    const data = await apiGet<Token[]>(`/users/me/tokens`);
    setTokens(data);
  } catch {
    setMessage(t.settings.ai.loadFailed);
  }
}
