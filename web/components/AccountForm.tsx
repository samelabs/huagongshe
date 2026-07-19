"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function AccountForm() {
  const router = useRouter();
  const [kind, setKind] = useState<"login" | "register">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <div className="tabs">
        <button className={kind === "login" ? "active" : ""} onClick={() => setKind("login")}>登录</button>
        <button className={kind === "register" ? "active" : ""} onClick={() => setKind("register")}>注册</button>
      </div>
      <form className="form-stack" onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true); setMessage("");
        const values = new FormData(event.currentTarget);
        const payload = kind === "login"
          ? { account: values.get("account"), password: values.get("password") }
          : { username: values.get("username"), email: values.get("email"), password: values.get("password") };
        const response = await fetch(`/api/community/${kind}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        if (response.ok) { router.push("/submit"); router.refresh(); return; }
        const error = await response.json().catch(() => null);
        setMessage(error?.detail || "操作失败，请稍后重试"); setBusy(false);
      }}>
        {kind === "register" ? (
          <>
            <label>用户名<input name="username" required minLength={2} maxLength={30} autoComplete="username" /></label>
            <label>邮箱<input name="email" type="email" required autoComplete="email" /></label>
          </>
        ) : <label>用户名或邮箱<input name="account" required autoComplete="username" /></label>}
        <label>密码<input name="password" type="password" required minLength={kind === "register" ? 10 : 1} autoComplete={kind === "login" ? "current-password" : "new-password"} /></label>
        {message && <p className="form-message bad">{message}</p>}
        <button className="button primary" disabled={busy}>{busy ? "处理中…" : kind === "login" ? "登录" : "创建账号"}</button>
      </form>
    </>
  );
}
