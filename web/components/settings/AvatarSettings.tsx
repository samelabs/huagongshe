"use client";

import { useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";
import { apiPost, apiDelete } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";

/** 头像设置（Step 11 Part D）：预览统一 ui/Avatar（无图首字回退）；
 *  上传/移除 primary loading 宽度锁定（IX-4）；结果 Toast（IX-2）。 */
export function AvatarSettings() {
  const t = useDictionary();
  const toast = useToast();
  const { user, ready, refresh } = useAccount();
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <LoginRequired text={t.settings.avatar.title} />;

  return <section className="form-section">
    <div className="form-section-head"><div><h2>{t.settings.avatar.title}</h2><p>{t.settings.avatar.desc}</p></div></div>
    <div className="avatar-settings-preview">
      <Avatar id={user.id} name={user.display_name || user.username} src={user.avatar_url} size={80} />
      <div><strong>{t.settings.avatar.current}</strong><small>{t.settings.avatar.hint}</small></div>
    </div>
    <form className="avatar-upload" onSubmit={async (event) => {
      event.preventDefault();
      if (uploading || removing) return;
      const form = event.currentTarget;
      const file = new FormData(form).get("image");
      if (!(file instanceof File) || !file.size) { toast.error(t.settings.avatar.selectFile); return; }
      if (file.size > 5 * 1024 * 1024) { toast.error(t.settings.avatar.tooLarge); return; }
      setUploading(true);
      try {
        await apiPost(`/users/me/avatar`, new FormData(form));
        await refresh();
        form.reset();
        toast.success(t.settings.avatar.updated);
      } catch {
        toast.error(t.settings.avatar.uploadFailed);
      } finally { setUploading(false); }
    }}>
      <Field label={t.settings.avatar.uploadLabel}>
        <Input name="image" type="file" accept="image/jpeg,image/png,image/webp" required disabled={uploading} />
      </Field>
      <Button type="submit" variant="primary" loading={uploading}>{uploading ? t.settings.avatar.uploading : t.settings.avatar.uploadBtn}</Button>
    </form>
    {user.avatar_url && (
      <div className="avatar-remove">
        <Button
          variant="danger"
          loading={removing}
          disabled={uploading}
          onClick={async () => {
            if (removing || uploading) return;
            setRemoving(true);
            try {
              await apiDelete(`/users/me/avatar`);
              await refresh();
              toast.success(t.settings.avatar.removed);
            } catch {
              toast.error(t.settings.avatar.removeFailed);
            } finally { setRemoving(false); }
          }}
        >
          {removing ? t.settings.avatar.processing : t.settings.avatar.removeBtn}
        </Button>
      </div>
    )}
  </section>;
}
