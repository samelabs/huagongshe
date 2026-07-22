"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/AccountContext";

export function AccountForm({ nextPath = "/me" }: { nextPath?: string }) {
  const router = useRouter();
  const { refresh } = useAccount();
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
        if (kind === "register" && values.get("password") !== values.get("confirm_password")) {
          setMessage("两次输入的密码不一致"); setBusy(false); return;
        }
        const payload = kind === "login"
          ? { account: values.get("account"), password: values.get("password") }
          : {
              username: values.get("username"), email: values.get("email"),
              password: values.get("password"), confirm_password: values.get("confirm_password"),
            };
        const response = await fetch(`/api/auth/${kind}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        if (response.ok) { await refresh(); router.push(nextPath); router.refresh(); return; }
        const error = await response.json().catch(() => null);
        setMessage(apiError(error?.detail)); setBusy(false);
      }}>
        {kind === "register" ? (
          <>
            <label>用户名<input name="username" required minLength={2} maxLength={30} autoComplete="username" /></label>
            <label>邮箱<input name="email" type="email" required autoComplete="email" /></label>
          </>
        ) : <label>用户名或邮箱<input name="account" required autoComplete="username" /></label>}
        <label>密码<input name="password" type="password" required minLength={kind === "register" ? 10 : 1} autoComplete={kind === "login" ? "current-password" : "new-password"} /></label>
        {kind === "register" && (
          <>
            <p className="field-hint">至少 10 位，并同时包含字母和数字。</p>
            <label>确认密码<input name="confirm_password" type="password" required minLength={10} autoComplete="new-password" /></label>
          </>
        )}
        {message && <p className="form-message bad">{message}</p>}
        <button className="button primary" disabled={busy}>{busy ? "处理中…" : kind === "login" ? "登录" : "创建账号"}</button>
      </form>
    </>
  );
}

function apiError(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => typeof item?.msg === "string" ? item.msg.replace(/^Value error,\s*/, "") : null).filter(Boolean).join("；") || "输入内容未通过校验";
  }
  return "操作失败，请稍后重试";
}
