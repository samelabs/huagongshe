"use client";

import { useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiPost } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";

/** 安全设置（Step 11 Part D）：同版式整理（Field/Input/Button loading），
 *  不新增功能——改密成功仍跳登录页（密码轮换安全流程），失败 Notice err。 */
export function SecuritySettings() {
  const t = useDictionary();
  const locale = useLocale();
  const { user, ready } = useAccount();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.security.loginHint} />;

  return <section className="form-section">
    <div className="form-section-head"><div><h2>{t.settings.security.title}</h2><p>{t.settings.security.desc}</p></div></div>
    <form className="form-fields" onSubmit={async (event) => {
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
      } catch {
        setMessage(t.settings.security.failed);
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
  </section>;
}
