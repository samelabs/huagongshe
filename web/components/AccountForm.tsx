"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { applyLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Segmented } from "@/components/ui/Segmented";
import zhCN from "@/lib/i18n/locales/zh-CN";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

/** 登录/注册表单（Step 11 §9.6）：ui 表单控件 + 错误 Notice err（写明原因，
 *  不暴露错误码，IX-12）；提交 primary lg（触控 ≥44px）。请求路径与
 *  字段 name 与旧版逐字一致（登录回跳/工具登录流依赖这些锚点）。 */
export function AccountForm({ nextPath = "/me" }: { nextPath?: string }) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const { refresh } = useAccount();
  const [kind, setKind] = useState<"login" | "register">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  // 用户名实时校验
  const [username, setUsername] = useState("");
  const latestCheck = useRef(0);
  const [usernameCheck, setUsernameCheck] = useState<{ status: "idle" | "checking" | "ok" | "taken" | "invalid"; msg: string }>({ status: "idle", msg: "" });

  const checkUsername = useCallback(async (value: string) => {
    const v = value.trim();
    if (v.length < 4) { setUsernameCheck({ status: "idle", msg: "" }); return; }
    const requestId = ++latestCheck.current;
    setUsernameCheck({ status: "checking", msg: t.auth.checking });
    try {
      const res = await fetch(`/api/auth/check-username?username=${encodeURIComponent(v)}`);
      if (!res.ok) throw new Error(); // 服务端故障不做判定(回 idle), 不误报"不可用"
      const data = await res.json();
      // A slower earlier probe must not overwrite the verdict for the
      // username currently typed.
      if (requestId !== latestCheck.current) return;
      if (!data.available) {
        // 服务端 reason 是固定中文契约串(/api/auth/check-username): "用户名已被使用" → taken。
        // 判定锚定 zh 字典常量(与 API 契约一致, 不随展示 locale 变), 提示文案用当前字典。
        const taken = data.reason === zhCN.auth.usernameTaken;
        setUsernameCheck({ status: taken ? "taken" : "invalid", msg: taken ? t.auth.usernameTaken : (data.reason || t.auth.usernameUnavailable) });
      } else {
        setUsernameCheck({ status: "ok", msg: t.auth.usernameAvailable });
      }
    } catch {
      if (requestId !== latestCheck.current) return;
      setUsernameCheck({ status: "idle", msg: "" });
    }
  }, [t]);

  // 防抖
  useEffect(() => {
    if (kind !== "register" || !username) { setUsernameCheck({ status: "idle", msg: "" }); return; }
    const timer = setTimeout(() => checkUsername(username), 400);
    return () => clearTimeout(timer);
  }, [username, kind, checkUsername]);

  const usernameState = usernameCheck.status;
  const usernameHelp = usernameState === "idle" ? t.auth.usernameRule : usernameCheck.msg;

  return (
    <>
      <Segmented
        ariaLabel={t.auth.title}
        value={kind}
        onChange={(next) => { setKind(next); setMessage(""); }}
        options={[
          { value: "login", label: t.auth.title },
          { value: "register", label: t.auth.registerTitle },
        ]}
      />
      <form className="form-stack" onSubmit={async (event) => {
        event.preventDefault();
        if (busy) return;  // loading 不落 disabled：提交重入在 handler 拦截
        setBusy(true); setMessage("");
        const values = new FormData(event.currentTarget);
        if (kind === "register" && values.get("password") !== values.get("confirm_password")) {
          setMessage(t.auth.mismatch); setBusy(false); return;
        }
        if (kind === "register" && !/^(?=.*[A-Za-z])(?=.*\d).{8,}$/.test(String(values.get("password") || ""))) {
          setMessage(t.auth.weakPassword); setBusy(false); return;
        }
        if (kind === "register" && usernameCheck.status === "taken") {
          setMessage(t.auth.usernameTaken); setBusy(false); return;
        }
        if (kind === "register" && usernameCheck.status === "invalid") {
          setMessage(usernameCheck.msg || t.auth.usernameUnavailable); setBusy(false); return;
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
          if (response.ok) { await refresh(); router.push(applyLocale(nextPath, locale)); router.refresh(); return; }
          const error = await response.json().catch(() => null);
          setMessage(apiError(error?.detail, t));
        } catch {
          setMessage(t.auth.networkFailed);
        } finally {
          setBusy(false);
        }
      }}>
        {kind === "register" ? (
          <>
            <Field label={t.auth.username} required help={usernameHelp} error={usernameState === "taken" || usernameState === "invalid" ? usernameCheck.msg : undefined}>
              <Input
                name="username"
                required minLength={4} maxLength={30}
                pattern="[a-z0-9_]{4,30}"
                title={t.auth.usernameRule}
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                invalid={usernameState === "taken" || usernameState === "invalid"}
              />
            </Field>
            <Field label={t.auth.email} required>
              <Input name="email" type="email" required autoComplete="email" />
            </Field>
          </>
        ) : (
          <Field label={t.auth.usernameOrEmail} required>
            <Input name="account" required autoComplete="username" />
          </Field>
        )}
        <Field label={t.auth.password} required help={kind === "register" ? t.auth.passwordHint : undefined}>
          <Input name="password" type="password" required minLength={kind === "register" ? 8 : 1} autoComplete={kind === "login" ? "current-password" : "new-password"} />
        </Field>
        {kind === "register" && (
          <Field label={t.auth.confirmPassword} required>
            <Input name="confirm_password" type="password" required minLength={8} autoComplete="new-password" />
          </Field>
        )}
        <Button type="submit" variant="primary" size="lg" loading={busy}>{busy ? t.auth.submitting : t.auth.submit(kind)}</Button>
      </form>
      {message && <Notice tone="err">{message}</Notice>}
    </>
  );
}

function apiError(detail: unknown, labels: Dictionary) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => typeof item?.msg === "string" ? item.msg.replace(/^Value error,\s*/, "") : null).filter(Boolean).join("；") || labels.auth.validationError;
  }
  return labels.auth.failed;
}
