"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/AccountContext";
import t from "@/lib/i18n";

export function AccountForm({ nextPath = "/me" }: { nextPath?: string }) {
  const router = useRouter();
  const { refresh } = useAccount();
  const [kind, setKind] = useState<"login" | "register">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  // 用户名实时校验
  const [username, setUsername] = useState("");
  const [usernameCheck, setUsernameCheck] = useState<{ status: "idle" | "checking" | "ok" | "taken" | "invalid"; msg: string }>({ status: "idle", msg: "" });

  const checkUsername = useCallback(async (value: string) => {
    const v = value.trim();
    if (v.length < 4) { setUsernameCheck({ status: "idle", msg: "" }); return; }
    setUsernameCheck({ status: "checking", msg: "检查中…" });
    try {
      const res = await fetch(`/api/auth/check-username?username=${encodeURIComponent(v)}`);
      const data = await res.json();
      if (!data.available) {
        setUsernameCheck({ status: data.reason === "用户名已被使用" ? "taken" : "invalid", msg: data.reason || "不可用" });
      } else {
        setUsernameCheck({ status: "ok", msg: "可用的用户名" });
      }
    } catch {
      setUsernameCheck({ status: "idle", msg: "" });
    }
  }, []);

  // 防抖
  useEffect(() => {
    if (kind !== "register" || !username) { setUsernameCheck({ status: "idle", msg: "" }); return; }
    const timer = setTimeout(() => checkUsername(username), 400);
    return () => clearTimeout(timer);
  }, [username, kind, checkUsername]);

  return (
    <>
      <div className="tabs">
        <button type="button" className={kind === "login" ? "active" : ""} disabled={busy} onClick={() => { setKind("login"); setMessage(""); }}>{t.auth.title}</button>
        <button type="button" className={kind === "register" ? "active" : ""} disabled={busy} onClick={() => { setKind("register"); setMessage(""); }}>{t.auth.registerTitle}</button>
      </div>
      <form className="form-stack" onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true); setMessage("");
        const values = new FormData(event.currentTarget);
        if (kind === "register" && values.get("password") !== values.get("confirm_password")) {
          setMessage(t.auth.mismatch); setBusy(false); return;
        }
        if (kind === "register" && !/^(?=.*[A-Za-z])(?=.*\d).{8,}$/.test(String(values.get("password") || ""))) {
          setMessage(t.auth.weakPassword); setBusy(false); return;
        }
        if (kind === "register" && usernameCheck.status !== "ok") {
          setMessage("请先输入可用的用户名"); setBusy(false); return;
        }
        const payload = kind === "login"
          ? { account: values.get("account"), password: values.get("password") }
          : {
              username: values.get("username"), email: values.get("email"),
              password: values.get("password"), confirm_password: values.get("confirm_password"),
            };
        try {
          const response = await fetch(`/api/auth/${kind}`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
          });
          if (response.ok) { await refresh(); router.push(nextPath); router.refresh(); return; }
          const error = await response.json().catch(() => null);
          setMessage(apiError(error?.detail));
        } catch {
          setMessage(t.auth.networkFailed);
        } finally {
          setBusy(false);
        }
      }}>
        {kind === "register" ? (
          <>
            <label>{t.auth.username}
              <input
                name="username"
                required minLength={4} maxLength={30}
                pattern="[a-z0-9_]{4,30}"
                title="4–30 位小写字母、数字或下划线"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className={usernameCheck.status === "taken" || usernameCheck.status === "invalid" ? "input-error" : usernameCheck.status === "ok" ? "input-ok" : ""}
              />
            </label>
            <p className={`field-hint ${usernameCheck.status === "ok" ? "good" : usernameCheck.status === "taken" || usernameCheck.status === "invalid" ? "bad" : ""}`}>
              {usernameCheck.msg || "4–30 位小写字母、数字或下划线"}
            </p>
            <label>{t.auth.email}<input name="email" type="email" required autoComplete="email" /></label>
          </>
        ) : <label>{t.auth.usernameOrEmail}<input name="account" required autoComplete="username" /></label>}
        <label>{t.auth.password}<input name="password" type="password" required minLength={kind === "register" ? 8 : 1} autoComplete={kind === "login" ? "current-password" : "new-password"} /></label>
        {kind === "register" && (
          <>
            <p className="field-hint">{t.auth.passwordHint}</p>
            <label>{t.auth.confirmPassword}<input name="confirm_password" type="password" required minLength={8} autoComplete="new-password" /></label>
          </>
        )}
        {message && <p className="form-message bad">{message}</p>}
        <button type="submit" className="button primary" disabled={busy}>{busy ? t.auth.submitting : t.auth.submit(kind)}</button>
      </form>
    </>
  );
}

function apiError(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => typeof item?.msg === "string" ? item.msg.replace(/^Value error,\s*/, "") : null).filter(Boolean).join("；") || t.auth.validationError;
  }
  return t.auth.failed;
}
