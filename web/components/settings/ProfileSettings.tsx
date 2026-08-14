"use client";

import { useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPatch, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type Profile = {
  display_name: string;
  bio: string;
  email: string;
  location: string;
  institution: string;
  title: string;
  website: string;
  orcid: string;
};

const EMPTY: Profile = {
  display_name: "", bio: "", email: "", location: "",
  institution: "", title: "", website: "", orcid: "",
};

export function ProfileSettings() {
  const { user, ready, refresh } = useAccount();
  const [profile, setProfile] = useState<Profile>(EMPTY);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"ok" | "bad">("ok");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiGet<Record<string, string>>(`/users/${encodeURIComponent(user.username)}`).then((value) => {
      if (!active) return;
      setProfile({
        display_name: value.display_name || "",
        bio: value.bio || "",
        email: value.email || "",
        location: value.location || "",
        institution: value.institution || "",
        title: value.title || "",
        website: value.website || "",
        orcid: value.orcid || "",
      });
    }).catch(() => {});
    return () => { active = false; };
  }, [user]);

  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.profile.loginHint} />;

  function update(field: keyof Profile, value: string) {
    setProfile((prev) => ({ ...prev, [field]: value }));
  }

  return <section className="form-section">
    <div className="form-section-head"><span>{t.settings.profile.kicker}</span><div><h2>{t.settings.profile.title}</h2><p>{t.settings.profile.desc}</p></div></div>

    <form className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      setBusy(true); setMessage("");
      try {
        await apiPatch(`/users/me`, JSON.stringify(profile));
        await refresh();
        setMessageKind("ok"); setMessage(t.settings.profile.saved);
      } catch (err) {
        setMessageKind("bad");
        setMessage(err instanceof ApiError && err.status === 400 ? t.settings.profile.saveFailed : t.common.networkError);
      } finally { setBusy(false); }
    }}>
      <label>{t.settings.profile.username}<span className="field-hint">@{user.username}（{t.settings.profile.usernameHint}）</span></label>
      <a className="settings-preview-link" href={`/user/${encodeURIComponent(user.username)}`} target="_blank" rel="noopener noreferrer">{t.settings.profile.previewProfile}</a>

      <div className="form-fields two-columns">
        <label>{t.settings.profile.displayName}<input value={profile.display_name} onChange={(e) => update("display_name", e.target.value)} maxLength={80} required /></label>
        <label>{t.settings.profile.email}<input type="email" value={profile.email} onChange={(e) => update("email", e.target.value)} maxLength={200} required /></label>
      </div>

      <div className="form-fields two-columns">
        <label>{t.settings.profile.institution}<input value={profile.institution} onChange={(e) => update("institution", e.target.value)} maxLength={200} placeholder={t.settings.profile.institutionPH} /></label>
        <label>{t.settings.profile.fieldTitle}<input value={profile.title} onChange={(e) => update("title", e.target.value)} maxLength={200} placeholder={t.settings.profile.titlePH} /></label>
      </div>

      <div className="form-fields two-columns">
        <label>{t.settings.profile.location}<input value={profile.location} onChange={(e) => update("location", e.target.value)} maxLength={100} placeholder={t.settings.profile.locationPH} /></label>
        <label>{t.settings.profile.website}<input value={profile.website} onChange={(e) => update("website", e.target.value)} maxLength={500} placeholder={t.settings.profile.websitePH} /></label>
      </div>

      <label>{t.settings.profile.orcid}<span className="field-hint">{t.settings.profile.orcidHint}</span><input value={profile.orcid} onChange={(e) => update("orcid", e.target.value)} maxLength={19} placeholder={t.settings.profile.orcidPH} /></label>

      <label>{t.settings.profile.bio}<textarea value={profile.bio} onChange={(e) => update("bio", e.target.value)} maxLength={500} rows={4} placeholder={t.settings.profile.bioPH} /></label>

      <button type="submit" className="button primary" disabled={busy}>{busy ? t.settings.profile.saving : t.settings.profile.saveBtn}</button>
    </form>
    {message && <p className={`form-message ${messageKind}`}>{message}</p>}
  </section>;
}
