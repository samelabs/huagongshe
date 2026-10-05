"use client";

import { useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiPost, apiDelete } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

export function AvatarSettings() {
  const t = useDictionary();
  const locale = useLocale();
  const { user, ready, refresh } = useAccount();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.avatar.title} />;

  return <section className="form-section">
    <div className="form-section-head"><span>{t.settings.avatar.kicker}</span><div><h2>{t.settings.avatar.title}</h2><p>{t.settings.avatar.desc}</p></div></div>
    <div className="avatar-settings-preview">{user.avatar_url ? <img src={user.avatar_url} alt={t.settings.avatar.current} /> : <span>{user.display_name.slice(0, 1)}</span>}<div><strong>{t.settings.avatar.current}</strong><small>{t.settings.avatar.hint}</small></div></div>
    <form className="avatar-upload" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      const form = event.currentTarget;
      const file = new FormData(form).get("image");
      if (!(file instanceof File) || !file.size) { setMessage(t.settings.avatar.selectFile); return; }
      if (file.size > 5 * 1024 * 1024) { setMessage(t.settings.avatar.tooLarge); return; }
      setBusy(true); setMessage("");
      try {
        await apiPost(`/users/me/avatar`, new FormData(form));
        await refresh();
        form.reset();
        setMessage(t.settings.avatar.updated);
      } catch {
        setMessage(t.settings.avatar.uploadFailed);
      } finally { setBusy(false); }
    }}>
      <input name="image" type="file" accept="image/jpeg,image/png,image/webp" required disabled={busy} />
      <button type="submit" className="button primary small" disabled={busy}>{busy ? t.settings.avatar.uploading : t.settings.avatar.uploadBtn}</button>
    </form>
    {user.avatar_url && (
      <div className="avatar-remove">
        <button type="button" className="button danger small" disabled={busy} onClick={async () => {
          if (busy) return;
          setBusy(true); setMessage("");
          try {
            await apiDelete(`/users/me/avatar`);
            await refresh();
            setMessage(t.settings.avatar.removed);
          } catch {
            setMessage(t.settings.avatar.removeFailed);
          } finally { setBusy(false); }
        }}>{busy ? t.settings.avatar.processing : t.settings.avatar.removeBtn}</button>
      </div>
    )}
    {message && <p className={message === t.settings.avatar.updated || message === t.settings.avatar.removed ? "form-message ok" : "form-message bad"}>{message}</p>}
  </section>;
}
