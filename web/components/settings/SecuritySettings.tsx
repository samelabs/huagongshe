"use client";

import { useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

export function SecuritySettings() {
  const { user, ready } = useAccount();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后修改密码。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>SECURITY</span><div><h2>修改密码</h2><p>修改后将注销全部会话并撤销现有 AI 授权。</p></div></div>
    <form className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      if (busy) return;
      const values = new FormData(event.currentTarget);
      const password = String(values.get("new_password") || "");
      if (password !== values.get("confirm_password")) { setMessage("两次输入的新密码不一致。"); return; }
      if (!/^(?=.*[A-Za-z])(?=.*\d).{10,}$/.test(password)) { setMessage("新密码至少 10 位，并同时包含字母和数字。"); return; }
      setBusy(true); setMessage("");
      try {
        const response = await fetch("/api/users/me/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: values.get("current_password"), new_password: password, confirm_password: values.get("confirm_password") }) });
        if (response.ok) { window.location.assign("/login"); return; }
        setMessage("密码修改失败，请核对当前密码和新密码要求。");
      } catch {
        setMessage("网络连接失败，请稍后重试。");
      } finally { setBusy(false); }
    }}>
      <label>当前密码<input name="current_password" type="password" autoComplete="current-password" required /></label>
      <label>新密码<input name="new_password" type="password" autoComplete="new-password" minLength={10} required /></label>
      <label>确认新密码<input name="confirm_password" type="password" autoComplete="new-password" minLength={10} required /></label>
      <button type="submit" className="button primary small" disabled={busy}>{busy ? "修改中…" : "修改密码"}</button>
    </form>
    {message && <p className="form-message bad">{message}</p>}
  </section>;
}
