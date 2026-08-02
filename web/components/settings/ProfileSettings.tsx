"use client";

import { useEffect, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

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
    fetch(`/api/users/${encodeURIComponent(user.username)}`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) return;
      const value = await response.json();
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
    });
  }, [user]);

  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后管理个人资料。" />;

  function update(field: keyof Profile, value: string) {
    setProfile((prev) => ({ ...prev, [field]: value }));
  }

  return <section className="form-section">
    <div className="form-section-head"><span>PROFILE</span><div><h2>个人资料</h2><p>完善资料有助于其他研究者了解和引用你的工作。</p></div></div>

    <form className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      setBusy(true); setMessage("");
      try {
        const response = await fetch("/api/users/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          setMessageKind("bad"); setMessage(body?.detail || "保存失败，请检查内容后重试。");
          return;
        }
        await refresh();
        setMessageKind("ok"); setMessage("资料已保存。");
      } catch {
        setMessageKind("bad"); setMessage("网络连接失败，请稍后重试。");
      } finally { setBusy(false); }
    }}>
      <label>用户名<span className="field-hint">@{user.username}（不可修改）</span></label>

      <div className="form-fields two-columns">
        <label>展示名称<input value={profile.display_name} onChange={(e) => update("display_name", e.target.value)} maxLength={80} required /></label>
        <label>邮箱<input type="email" value={profile.email} onChange={(e) => update("email", e.target.value)} maxLength={200} required /></label>
      </div>

      <div className="form-fields two-columns">
        <label>所在机构<input value={profile.institution} onChange={(e) => update("institution", e.target.value)} maxLength={200} placeholder="如：清华大学化学系" /></label>
        <label>职称/研究方向<input value={profile.title} onChange={(e) => update("title", e.target.value)} maxLength={200} placeholder="如：有机合成博士生" /></label>
      </div>

      <div className="form-fields two-columns">
        <label>所在城市<input value={profile.location} onChange={(e) => update("location", e.target.value)} maxLength={100} placeholder="如：北京" /></label>
        <label>个人主页<input value={profile.website} onChange={(e) => update("website", e.target.value)} maxLength={500} placeholder="如：https://lab.example.edu" /></label>
      </div>

      <label>ORCID<span className="field-hint">学术研究者标识符，16 位数字</span><input value={profile.orcid} onChange={(e) => update("orcid", e.target.value)} maxLength={19} placeholder="如：0000-0000-0000-0000" /></label>

      <label>简介<textarea value={profile.bio} onChange={(e) => update("bio", e.target.value)} maxLength={500} rows={4} placeholder="介绍你的研究方向和兴趣" /></label>

      <button type="submit" className="button primary" disabled={busy}>{busy ? "保存中…" : "保存资料"}</button>
    </form>
    {message && <p className={`form-message ${messageKind}`}>{message}</p>}
  </section>;
}
