"use client";

import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

export function ProfileSettings() {
  const { user, ready, refresh } = useAccount();
  const [profile, setProfile] = useState({ display_name: "", bio: "" });
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"ok" | "bad">("ok");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    fetch(`/api/users/${encodeURIComponent(user.username)}`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) return;
      const value = await response.json();
      setProfile({ display_name: value.display_name, bio: value.bio || "" });
    });
  }, [user]);

  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后管理公开资料。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>PROFILE</span><div><h2>公开资料</h2><p>展示名称和简介将显示在公开主页和反应页面。</p></div></div>
    <form className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      setBusy(true); setMessage("");
      try {
        const response = await fetch("/api/users/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
        if (!response.ok) throw new Error();
        await refresh();
        setMessageKind("ok"); setMessage("资料已保存。");
      } catch {
        setMessageKind("bad"); setMessage("资料保存失败，内容仍保留在本页，请稍后重试。");
      } finally { setBusy(false); }
    }}>
      <label>展示名称<input value={profile.display_name} onChange={(event) => setProfile((value) => ({ ...value, display_name: event.target.value }))} maxLength={80} required /></label>
      <label>简介<textarea value={profile.bio} onChange={(event) => setProfile((value) => ({ ...value, bio: event.target.value }))} maxLength={500} rows={5} /></label>
      <button type="submit" className="button primary small" disabled={busy}>{busy ? "保存中…" : "保存资料"}</button>
    </form>
    {message && <p className={`form-message ${messageKind}`}>{message}</p>}
  </section>;
}
