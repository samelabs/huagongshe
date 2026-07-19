"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type User = { id: number; username: string; email: string; role: "member" | "editor" | "admin" };

export function HeaderAccount() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/community/me", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() as Promise<User> : null)
      .then((value) => { if (active) { setUser(value); setReady(true); } })
      .catch(() => { if (active) setReady(true); });
    return () => { active = false; };
  }, []);

  async function logout() {
    await fetch("/api/community/logout", { method: "POST" });
    setUser(null);
    router.push("/");
    router.refresh();
  }

  return (
    <nav aria-label="主导航">
      <Link href="/submit">提交</Link>
      {user && (user.role === "admin" || user.role === "editor") && <Link href="/admin">审核</Link>}
      {user ? (
        <div className="account-nav">
          <span title={user.email}>{user.username}</span>
          <button type="button" onClick={logout}>退出</button>
        </div>
      ) : ready ? (
        <Link href="/login" className="login-link">登录</Link>
      ) : <span className="nav-placeholder" aria-hidden="true" />}
    </nav>
  );
}
