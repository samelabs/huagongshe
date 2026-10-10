"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPost, apiDelete, ApiError } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { CodeField } from "@/components/ui/CodeField";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, Input, Select } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useToast } from "@/components/ui/Toast";
import { IconPlug } from "@/components/ui/icons";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

type Token = { id: number; name: string; token_prefix: string; token_plain: string | null; created_at: string; expires_at: string | null; last_used_at: string | null };
type CreatedToken = { token: string };

/** AI Key 管理（Step 11 Part D）：
 *  - 撤销走 ConfirmDialog（IX-3：问句标题 + 写明 Key 名称/前缀 + 「撤销 Key」
 *    danger 确认 + 默认焦点「取消」+ Esc 回焦触发按钮）
 *  - 明文 Key 与列表可复制 Key 统一 CodeField（IX-7 播报 + ✓ 1.5s）
 *  - 「只显示一次」用 Notice warn；空列表 EmptyState + 下一步（IX-8）
 *  - 撤销失败 Toast err、行保持原状 */
export function ApiTokenSettings() {
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();
  const confirm = useConfirm();
  const { user, ready } = useAccount();
  const [tokens, setTokens] = useState<Token[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

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
    } catch {
      toast.error(t.settings.ai.revokeFailed);  // 行保持原状
    } finally {
      setRevokingId(null);
    }
  }

  return <section className="form-section">
    <div className="form-section-head"><div><h2>{t.settings.ai.title}</h2><p>{t.settings.ai.desc}</p></div></div>
    <form className="token-create" onSubmit={async (event) => {
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
        if (error instanceof ApiError && error.status === 409) setMessage(t.settings.ai.limitReached);
        else if (error instanceof ApiError && error.status === 401) setMessage(t.settings.ai.relogin);
        else if (error instanceof ApiError && error.status === 502) setMessage(t.settings.ai.upstreamDown);
        else if (error instanceof ApiError && (error.status === 400 || error.status === 422)) setMessage(t.settings.ai.createFailed);
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
        <Notice tone="warn">{t.settings.ai.onceNotice}</Notice>
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
        return <article key={token.id}>
          <div>
            <strong>{token.name}</strong>
            <span>{token.token_prefix}… · {status}</span>
            <small>{token.last_used_at ? t.settings.ai.lastUsed(new Date(token.last_used_at).toLocaleString(locale)) : t.settings.ai.neverUsed} · {expires}</small>
            {token.token_plain && <CodeField value={token.token_plain} copyLabel={t.settings.ai.copyToken} className="token-row-code" />}
          </div>
          <div className="token-actions">
            <Button
              variant="secondary"
              size="sm"
              loading={revokingId === token.id}
              disabled={revokingId !== null && revokingId !== token.id}
              onClick={async () => {
                // IX-3：不可逆操作二次确认（默认焦点「取消」，Esc 回焦到此按钮）
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
      <Link className="api-guide-link" href={withLocale("/guide", locale)}>{t.settings.ai.guideLink}</Link>
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
