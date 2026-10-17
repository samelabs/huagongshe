"use client";

import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiGet, apiPatch, ApiError, apiErrorMessage } from "@/lib/api";
import { mergeLateProfile, type ProfileFields } from "@/lib/profileMerge";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useToast } from "@/components/ui/Toast";

type Profile = ProfileFields;

const EMPTY: Profile = {
  display_name: "", bio: "", email: "", location: "",
  institution: "", title: "", website: "", orcid: "",
};

/** 资料设置（）：ui Field/Input/Textarea；保存结果 Toast；
 * 提交 primary + loading 宽度锁定。字段错误显示在输入框下方。 */
export function ProfileSettings() {
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();
  const { user, ready, refresh } = useAccount();
  const [profile, setProfile] = useState<Profile>(EMPTY);
  /** ZX（迟到 GET 按字段合并, 原 / 整体丢弃）：只记录用户
   * 改过的字段 —— GET 返回时这些字段保留当前输入, 未改字段回填服务端值 */
  const touchedRef = useRef<Set<keyof Profile>>(new Set());
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Profile, string>>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiGet<Record<string, string>>(`/users/${encodeURIComponent(user.username)}`).then((value) => {
      if (!active) return;
      setProfile((prev) => mergeLateProfile(prev, value, touchedRef.current));
    }).catch(() => {});
    return () => { active = false; };
  }, [user]);

  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.profile.loginHint} />;

  function update(field: keyof Profile, value: string) {
    touchedRef.current.add(field);
    setProfile((prev) => ({ ...prev, [field]: value }));
    setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
  }

  return <section className="form-section">
    <div className="form-section-head"><p>{t.settings.profile.desc}</p></div>

    <form method="post" className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      const errors: Partial<Record<keyof Profile, string>> = {};
      // 网址与 API 同一规则（api/schemas/users.py clean_website）：裸域名自动补
      // https:// 后按完整网址校验；不合规在字段下方说明原因，不发请求。
      const website = profile.website.trim();
      let normalizedWebsite = website;
      if (website && !/^https?:\/\//i.test(website)) {
        if (/^[^\s/?#]+\.[^\s/?#]+(\/.*)?$/.test(website)) normalizedWebsite = `https://${website}`;
        else errors.website = t.settings.profile.websiteInvalid;
      }
      if (website && !errors.website) {
        let host: string | null = null;
        try { host = new URL(normalizedWebsite).hostname; } catch { host = null; }
        if (!host || !host.includes(".")) errors.website = t.settings.profile.websiteInvalid;
      }
      if (!errors.display_name && !profile.display_name.trim()) errors.display_name = t.settings.profile.requiredHint;
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(profile.email.trim())) errors.email = t.settings.profile.emailHint;
      // ORCID 与 API 同口径（api/schemas/users.py clean_orcid）：去非 [\dXx] 后 16 位（末位可 X）；
      // 带连字符与纯数字两种写法都放行 —— 前端不得比 API 更严。
      if (profile.orcid && !/^\d{15}[\dX]$/.test(profile.orcid.replace(/[^\dXx]/g, ""))) errors.orcid = t.settings.profile.orcidHint;
      setFieldErrors(errors);
      if (Object.keys(errors).length > 0) return;
      setBusy(true);
      // 新结果出现前清掉旧提示：错误提示不会自动消失，若保留会在成功提示
      // 淡出后继续留在屏幕上，看起来像保存成功后又弹出失败。
      toast.dismissAll();
      try {
        await apiPatch(`/users/me`, JSON.stringify({ ...profile, website: normalizedWebsite }));
        await refresh();
        toast.success(t.settings.profile.saved);
      } catch (err) {
        // 字段校验错误按字段展示；其余错误用统一文案提示。
        if (err instanceof ApiError && err.detailKind === "invalid_field") {
          const { detail: reason } = err;
          const field = err.detailField as keyof Profile | undefined;
          if (field && field in EMPTY) setFieldErrors({ [field]: reason ?? t.settings.profile.websiteInvalid });
          else toast.error(apiErrorMessage(err, t, t.settings.profile.saveFailed));
        } else {
          toast.error(apiErrorMessage(err, t, t.settings.profile.saveFailed));
        }
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
        <Field label={t.settings.profile.website} error={fieldErrors.website}>
          <Input value={profile.website} onChange={(e) => update("website", e.target.value)} maxLength={500} placeholder={t.settings.profile.websitePH} invalid={Boolean(fieldErrors.website)} />
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
