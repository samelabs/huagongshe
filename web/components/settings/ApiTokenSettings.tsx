"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPost, apiDelete, ApiError, apiErrorMessage } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { CodeField } from "@/components/ui/CodeField";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { CopyButton } from "@/components/ui/CopyButton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, Input, Select } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useToast } from "@/components/ui/Toast";
import { IconPlug } from "@/components/ui/icons";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

type Token = { id: number; name: string; token_prefix: string; token: string | null; created_at: string; expires_at: string | null; last_used_at: string | null };
type CreatedToken = { token: string };

/** AI Key 管理：
 * - AI Key 明文保存，本人可随时在设置页查看、复制（每账号最多 5 个）。
 * - 列表行内默认遮罩（前缀 + ••••），提供「显示/隐藏」和 CopyButton。
 * - 历史无明文 Key（null）不显示复制，行内提示无法再次查看。
 * - 撤销走 ConfirmDialog（危险操作确认 + Esc 回焦触发按钮）。 */
export function ApiTokenSettings() {
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();
  const confirm = useConfirm();
  const { user, ready } = useAccount();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [revealedIds, setRevealedIds] = useState<Set<number>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  function toggleReveal(id: number) {
    setRevealedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiGet<Token[]>(`/users/me/tokens`).then((data) => {
      if (active) { setTokens(data); setLoaded(true); }
    }).catch(() => { if (active) setMessage(t.settings.ai.loadFailed); });
    return () => { active = false; };
  }, [user, t]);

  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.ai.loginHint} />;

  async function revoke(token: Token) {
    setRevokingId(token.id); setMessage("");
    try {
      await apiDelete(`/users/me/tokens/${token.id}`);
      setTokens((prev) => prev.filter((row) => row.id !== token.id));
      toast.success(t.settings.ai.revokedToast(token.name));
    } catch (err) {
      toast.error(apiErrorMessage(err, t, t.settings.ai.revokeFailed));  // 行保持原状
    } finally {
      setRevokingId(null);
    }
  }

  return <section className="form-section">
    <div className="form-section-head"><div><p>{t.settings.ai.desc}</p></div></div>
    <form method="post" className="token-create" onSubmit={async (event) => {
      event.preventDefault();
      if (creating) return;
      const form = event.currentTarget;
      setCreatedToken(null);
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
        await loadTokens(setTokens, setMessage, t);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) setMessage(apiErrorMessage(error, t, t.settings.ai.limitReached));
        else if (error instanceof ApiError && error.status === 401) setMessage(apiErrorMessage(error, t, t.settings.ai.relogin));
        else if (error instanceof ApiError && error.status === 502) setMessage(t.settings.ai.upstreamDown);
        else if (error instanceof ApiError && (error.status === 400 || error.status === 422)) setMessage(apiErrorMessage(error, t, t.settings.ai.createFailed));
        else setMessage(t.common.networkError);
      } finally { setCreating(false); }
    }}>
      <Field label={t.settings.ai.nameLabel} required className="token-create-name">
        <Input name="name" placeholder={t.settings.ai.placeholder} required maxLength={80} disabled={creating} ref={nameRef} />
      </Field>
      <Field label={t.settings.ai.daysLabel} className="token-create-days">
        <Select name="days" defaultValue="90" disabled={creating}>
          <option value="30">{t.settings.ai.days30}</option>
          <option value="90">{t.settings.ai.days90}</option>
          <option value="365">{t.settings.ai.days365}</option>
          <option value="">{t.settings.ai.noExpiry}</option>
        </Select>
      </Field>
      <Button type="submit" variant="primary" loading={creating}>{creating ? t.settings.ai.creating : t.settings.ai.createBtn}</Button>
    </form>
    {createdToken && (
      <div className="token-secret">
        <strong>{t.settings.ai.created}</strong>
        <CodeField value={createdToken.token} copyLabel={t.settings.ai.copyToken} multiline />
        <p className="token-secret-hint">{t.settings.ai.copyHint}</p>
      </div>
    )}
    {message && <Notice tone="err">{message}</Notice>}
    {loaded && tokens.length === 0 ? (
      <EmptyState
        icon={<IconPlug />}
        title={t.settings.ai.emptyTitle}
        action={{ label: t.settings.ai.emptyAction, onClick: () => nameRef.current?.focus() }}
      >
        {t.settings.ai.emptyDesc}
      </EmptyState>
    ) : (
      <div className="token-list">{tokens.map((token) => {
        const expired = Boolean(token.expires_at && new Date(token.expires_at).getTime() <= Date.now());
        const status = expired ? t.settings.ai.statusExpired : t.settings.ai.statusValid;
        const expires = token.expires_at ? t.settings.ai.expiresAt(new Date(token.expires_at).toLocaleDateString(locale)) : t.settings.ai.longTerm;
        const hasToken = typeof token.token === "string" && token.token.length > 0;
        const isRevealed = revealedIds.has(token.id);
        const displayValue = isRevealed ? token.token : `${token.token_prefix}••••`;

        return <article key={token.id}>
          <div>
            <strong>{token.name}</strong>
            {hasToken ? (
              <div className="token-row-secret">
                <code className="token-code">{displayValue}</code>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => toggleReveal(token.id)}
                >
                  {isRevealed ? t.settings.ai.hide : t.settings.ai.show}
                </Button>
                <CopyButton value={token.token!} ariaLabel={t.settings.ai.copyToken} />
                <span className="token-meta-status">· {status}</span>
              </div>
            ) : (
              <div className="token-row-null">
                <span>{token.token_prefix}… · {status}</span>
                <span className="token-null-desc">· {t.settings.ai.cannotViewAgain}</span>
              </div>
            )}
            <small>{token.last_used_at ? t.settings.ai.lastUsed(new Date(token.last_used_at).toLocaleString(locale)) : t.settings.ai.neverUsed} · {expires}</small>
          </div>
          <div className="token-actions">
            <Button
              variant="secondary"
              size="sm"
              loading={revokingId === token.id}
              disabled={revokingId !== null && revokingId !== token.id}
              onClick={async () => {
                // 不可逆操作二次确认（默认焦点「取消」，Esc 回焦到此按钮）
                const ok = await confirm({
                  title: t.settings.ai.revokeConfirmTitle,
                  body: t.settings.ai.revokeConfirmBody(token.name, token.token_prefix),
                  confirmLabel: t.settings.ai.revokeConfirmBtn,
                  tone: "danger",
                });
                if (ok) await revoke(token);
              }}
            >
              {revokingId === token.id ? t.settings.ai.revoking : t.settings.ai.revoke}
            </Button>
          </div>
        </article>;
      })}</div>
    )}
    <div className="token-help-links">
      <Link className="api-guide-link" href={withLocale("/mcp-guide", locale)}>{t.settings.ai.mcpGuideLink}</Link>
    </div>
  </section>;
}

async function loadTokens(
  setTokens: (ts: Token[]) => void,
  setMessage: (m: string) => void,
  labels: Dictionary,
) {
  try {
    const data = await apiGet<Token[]>(`/users/me/tokens`);
    setTokens(data);
  } catch {
    setMessage(labels.settings.ai.loadFailed);
  }
}
