"use client";

import { useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPatch, ApiError } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useToast } from "@/components/ui/Toast";

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

/** 资料设置（Step 11 Part D）：ui Field/Input/Textarea；保存结果 Toast（IX-2）；
 *  提交 primary + loading 宽度锁定（IX-4）。字段错误显示在输入框下方。 */
export function ProfileSettings() {
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();
  const { user, ready, refresh } = useAccount();
  const [profile, setProfile] = useState<Profile>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Profile, string>>>({});
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
    setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
  }

  return <section className="form-section">
    <div className="form-section-head"><div><h2>{t.settings.profile.title}</h2><p>{t.settings.profile.desc}</p></div></div>

    <form className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      const errors: Partial<Record<keyof Profile, string>> = {};
      if (!profile.display_name.trim()) errors.display_name = t.settings.profile.requiredHint;
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(profile.email)) errors.email = t.settings.profile.emailHint;
      if (profile.orcid && !/^\d{4}-\d{4}-\d{4}-[\dX]{4}$/.test(profile.orcid)) errors.orcid = t.settings.profile.orcidHint;
      setFieldErrors(errors);
      if (Object.keys(errors).length > 0) return;
      setBusy(true);
      try {
        await apiPatch(`/users/me`, JSON.stringify(profile));
        await refresh();
        toast.success(t.settings.profile.saved);
      } catch (err) {
        toast.error(err instanceof ApiError && err.status === 400 ? t.settings.profile.saveFailed : t.common.networkError);
      } finally { setBusy(false); }
    }}>
      <Field label={t.settings.profile.username} help={`@${user.username}（${t.settings.profile.usernameHint}）`} />
      <a className="settings-preview-link" href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)} target="_blank" rel="noopener noreferrer">{t.settings.profile.previewProfile}</a>

      <div className="form-fields two-columns">
        <Field label={t.settings.profile.displayName} required error={fieldErrors.display_name}>
          <Input value={profile.display_name} onChange={(e) => update("display_name", e.target.value)} maxLength={80} required invalid={Boolean(fieldErrors.display_name)} />
        </Field>
        <Field label={t.settings.profile.email} required error={fieldErrors.email}>
          <Input type="email" value={profile.email} onChange={(e) => update("email", e.target.value)} maxLength={200} required invalid={Boolean(fieldErrors.email)} />
        </Field>
      </div>

      <div className="form-fields two-columns">
        <Field label={t.settings.profile.institution}>
          <Input value={profile.institution} onChange={(e) => update("institution", e.target.value)} maxLength={200} placeholder={t.settings.profile.institutionPH} />
        </Field>
        <Field label={t.settings.profile.fieldTitle}>
          <Input value={profile.title} onChange={(e) => update("title", e.target.value)} maxLength={200} placeholder={t.settings.profile.titlePH} />
        </Field>
      </div>

      <div className="form-fields two-columns">
        <Field label={t.settings.profile.location}>
          <Input value={profile.location} onChange={(e) => update("location", e.target.value)} maxLength={100} placeholder={t.settings.profile.locationPH} />
        </Field>
        <Field label={t.settings.profile.website}>
          <Input value={profile.website} onChange={(e) => update("website", e.target.value)} maxLength={500} placeholder={t.settings.profile.websitePH} />
        </Field>
      </div>

      <Field label={t.settings.profile.orcid} help={t.settings.profile.orcidHint} error={fieldErrors.orcid}>
        <Input value={profile.orcid} onChange={(e) => update("orcid", e.target.value)} maxLength={19} placeholder={t.settings.profile.orcidPH} mono invalid={Boolean(fieldErrors.orcid)} />
      </Field>

      <Field label={t.settings.profile.bio}>
        <Textarea value={profile.bio} onChange={(e) => update("bio", e.target.value)} maxLength={500} rows={4} placeholder={t.settings.profile.bioPH} />
      </Field>

      <Button type="submit" variant="primary" loading={busy}>{busy ? t.settings.profile.saving : t.settings.profile.saveBtn}</Button>
    </form>
  </section>;
}
