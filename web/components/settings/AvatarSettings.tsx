"use client";

import { useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

export function AvatarSettings() {
  const { user, ready, refresh } = useAccount();
  const [message, setMessage] = useState("");
  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后设置头像。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>AVATAR</span><div><h2>头像</h2><p>图片将自动裁切、移除元数据并压缩为 WebP。</p></div></div>
    <div className="avatar-settings-preview">{user.avatar_url ? <img src={user.avatar_url} alt="当前头像" /> : <span>{user.display_name.slice(0, 1)}</span>}<div><strong>当前头像</strong><small>支持 JPEG、PNG 和 WebP，最大 5 MB。</small></div></div>
    <form className="avatar-upload" onSubmit={async (event) => {
      event.preventDefault();
      const response = await fetch("/api/users/me/avatar", { method: "POST", body: new FormData(event.currentTarget) });
      if (response.ok) await refresh();
      setMessage(response.ok ? "头像已更新。" : "头像上传失败，请检查图片大小和格式。");
    }}>
      <input name="image" type="file" accept="image/jpeg,image/png,image/webp" required />
      <button className="button primary small">上传头像</button>
    </form>
    {message && <p className={message === "头像已更新。" ? "form-message ok" : "form-message bad"}>{message}</p>}
  </section>;
}
