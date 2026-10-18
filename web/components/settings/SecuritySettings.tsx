"use client";

import { useCallback, useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPost, apiDelete, apiErrorMessage } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { EmptyState } from "@/components/ui/EmptyState";
import { Tag } from "@/components/ui/Tag";
import { TextLink } from "@/components/ui/TextLink";
import { IconPlug } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { relativeTime } from "@/components/workbench/shared";

type OAuthConnection = {
  client_id: string;
  client_name: string;
  scopes: string[];
  authorized_at: string;
  last_used_at: string | null;
};

/** 安全设置：修改密码 + 已连接的应用（OAuth）
 * 修改密码：成功跳登录页，失败 Notice err。
 * 已连接应用：列表、空态、撤销二次确认、DELETE 调用与 Toast。 */
export function SecuritySettings() {
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();
  const confirm = useConfirm();
  const { user, ready } = useAccount();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  // OAuth 已连接应用
  const [connections, setConnections] = useState<OAuthConnection[] | null>(null);
  const [connLoading, setConnLoading] = useState(true);
  const [connError, setConnError] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const loadConnections = useCallback(async () => {
    setConnLoading(true);
    setConnError(false);
    try {
      const data = await apiGet<{ items: OAuthConnection[] }>("/users/me/oauth-connections");
      setConnections(data?.items ?? []);
    } catch {
      setConnections(null);
      setConnError(true);
    } finally {
      setConnLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ready && user) {
      void loadConnections();
    }
  }, [ready, user, loadConnections]);

  async function handleRevoke(item: OAuthConnection) {
    if (revokingId) return;
    const ok = await confirm({
      title: t.settings.security.revokeConfirmTitle(item.client_name),
      body: t.settings.security.revokeConfirmBody,
      confirmLabel: t.settings.security.revokeConfirmBtn,
      tone: "danger",
    });
    if (!ok) return;

    setRevokingId(item.client_id);
    try {
      await apiDelete(`/users/me/oauth-connections/${encodeURIComponent(item.client_id)}`);
      setConnections((prev) => (prev ? prev.filter((c) => c.client_id !== item.client_id) : []));
      toast.success(t.settings.security.revokedToast(item.client_name));
    } catch (err) {
      toast.error(apiErrorMessage(err, t, t.settings.security.revokeFailed));
    } finally {
      setRevokingId(null);
    }
  }

  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.security.loginHint} />;

  return (
    <>
      <section className="form-section">
        <div className="form-section-head">
          <div>
            <h2>{t.settings.security.title}</h2>
            <p>{t.settings.security.desc}</p>
          </div>
        </div>
        <form method="post" className="form-fields" onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          const values = new FormData(event.currentTarget);
          const password = String(values.get("new_password") || "");
          if (password !== values.get("confirm_password")) { setMessage(t.settings.security.mismatch); return; }
          if (!/^(?=.*[A-Za-z])(?=.*\d).{8,}$/.test(password)) { setMessage(t.settings.security.requirement); return; }
          setBusy(true); setMessage("");
          try {
            await apiPost(`/users/me/password`, JSON.stringify({ current_password: values.get("current_password"), new_password: password, confirm_password: values.get("confirm_password") }));
            window.location.assign(withLocale("/login", locale)); return;
          } catch (err) {
            setMessage(apiErrorMessage(err, t, t.settings.security.failed));
          } finally { setBusy(false); }
        }}>
          <Field label={t.settings.security.current} required>
            <Input name="current_password" type="password" autoComplete="current-password" required />
          </Field>
          <Field label={t.settings.security.new} required help={t.settings.security.requirement}>
            <Input name="new_password" type="password" autoComplete="new-password" minLength={8} required />
          </Field>
          <Field label={t.settings.security.confirm} required>
            <Input name="confirm_password" type="password" autoComplete="new-password" minLength={8} required />
          </Field>
          <Button type="submit" variant="primary" loading={busy}>{busy ? t.settings.security.submitting : t.settings.security.submitBtn}</Button>
        </form>
        {message && <Notice tone="err">{message}</Notice>}
      </section>

      <section className="form-section">
        <div className="form-section-head">
          <div>
            <h2>{t.settings.security.oauthTitle}</h2>
            <p>{t.settings.security.oauthDesc}</p>
          </div>
        </div>

        {connLoading ? (
          <p className="context-loading">{t.common.loading}</p>
        ) : connError ? (
          <div className="oauth-conn-error">
            <Notice
              tone="err"
              action={{
                label: t.common.retry,
                onClick: () => { void loadConnections(); },
              }}
            >
              {t.settings.security.oauthLoadFailed}
            </Notice>
          </div>
        ) : connections && connections.length > 0 ? (
          <div className="oauth-conn-list">
            {connections.map((item) => (
              <article className="oauth-conn-row" key={item.client_id}>
                <div className="oauth-conn-main">
                  <div className="oauth-conn-head">
                    <strong className="oauth-conn-name">{item.client_name}</strong>
                    {item.scopes && item.scopes.length > 0 && (
                      <div className="oauth-conn-scopes">
                        {item.scopes.map((scope) => (
                          <Tag key={scope} tone="neutral">
                            {(t.settings.security.scopes as Record<string, string>)[scope] ?? scope}
                          </Tag>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="oauth-conn-meta">
                    <span>{t.settings.security.oauthAuthorized(relativeTime(item.authorized_at, locale))}</span>
                    <span aria-hidden="true">/</span>
                    <span>{item.last_used_at ? t.settings.security.oauthLastUsed(relativeTime(item.last_used_at, locale)) : t.settings.security.oauthNeverUsed}</span>
                  </div>
                </div>
                <div className="oauth-conn-actions">
                  <TextLink
                    disabled={revokingId === item.client_id}
                    onClick={() => handleRevoke(item)}
                  >
                    {revokingId === item.client_id ? t.settings.security.oauthRevoking : t.settings.security.oauthRevoke}
                  </TextLink>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={<IconPlug />} title={t.settings.security.oauthEmptyTitle}>
            {t.settings.security.oauthEmptyDesc}
          </EmptyState>
        )}
      </section>
    </>
  );
}
