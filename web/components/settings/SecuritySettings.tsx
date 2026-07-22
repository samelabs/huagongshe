"use client";

import { useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { LoginRequired } from "@/components/settings/SettingsAuth";

export function SecuritySettings() {
  const { user, ready } = useAccount();
  const [message, setMessage] = useState("");
  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <LoginRequired text="登录后修改密码。" />;

  return <section className="form-section">
    <div className="form-section-head"><span>SECURITY</span><div><h2>修改密码</h2><p>修改后将注销全部会话并撤销现有 AI 授权。</p></div></div>
    <form className="form-fields" onSubmit={async (event) => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      const response = await fetch("/api/users/me/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: values.get("current_password"), new_password: values.get("new_password"), confirm_password: values.get("confirm_password") }) });
      if (response.ok) window.location.href = "/login";
      else setMessage("密码修改失败，请核对当前密码和新密码要求。");
    }}>
      <label>当前密码<input name="current_password" type="password" autoComplete="current-password" required /></label>
      <label>新密码<input name="new_password" type="password" autoComplete="new-password" minLength={10} required /></label>
      <label>确认新密码<input name="confirm_password" type="password" autoComplete="new-password" minLength={10} required /></label>
      <button className="button primary small">修改密码</button>
    </form>
    {message && <p className="form-message bad">{message}</p>}
  </section>;
}
