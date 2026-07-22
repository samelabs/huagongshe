"use client";

import { useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

export function AvatarSettings() {
  const { user, ready, refresh } = useAccount();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后设置头像。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>AVATAR</span><div><h2>头像</h2><p>图片将自动裁切、移除元数据并压缩为 WebP。</p></div></div>
    <div className="avatar-settings-preview">{user.avatar_url ? <img src={user.avatar_url} alt="当前头像" /> : <span>{user.display_name.slice(0, 1)}</span>}<div><strong>当前头像</strong><small>支持 JPEG、PNG 和 WebP，最大 5 MB。</small></div></div>
    <form className="avatar-upload" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      const form = event.currentTarget;
      const file = new FormData(form).get("image");
      if (!(file instanceof File) || !file.size) { setMessage("请选择头像图片。"); return; }
      if (file.size > 5 * 1024 * 1024) { setMessage("图片不能超过 5 MB。"); return; }
      setBusy(true); setMessage("");
      try {
        const response = await fetch("/api/users/me/avatar", { method: "POST", body: new FormData(form) });
        if (!response.ok) throw new Error();
        await refresh();
        form.reset();
        setMessage("头像已更新。");
      } catch {
        setMessage("头像上传失败，请检查图片格式或稍后重试。");
      } finally { setBusy(false); }
    }}>
      <input name="image" type="file" accept="image/jpeg,image/png,image/webp" required disabled={busy} />
      <button type="submit" className="button primary small" disabled={busy}>{busy ? "上传中…" : "上传头像"}</button>
    </form>
    {message && <p className={message === "头像已更新。" ? "form-message ok" : "form-message bad"}>{message}</p>}
  </section>;
}
