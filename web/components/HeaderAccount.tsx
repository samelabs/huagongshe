"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type User = { id: number; username: string; display_name: string; email: string; avatar_url: string | null; role: "member" | "admin" };

export function HeaderAccount() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/users/me", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() as Promise<User> : null)
      .then((value) => { if (active) { setUser(value); setReady(true); } })
      .catch(() => { if (active) setReady(true); });
    return () => { active = false; };
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    setUser(null);
    router.push("/");
    router.refresh();
  }

  return (
    <nav aria-label="主导航">
      <Link href="/submit" className="nav-contribute">发布反应</Link>
      {user?.role === "admin" && <Link href="/admin" className="nav-review">平台管理</Link>}
      {user ? (
        <div className="account-nav">
          <Link href="/me" className="account-identity" title={user.email}>
            {user.avatar_url ? <img src={user.avatar_url.replace(".webp", "-128.webp")} alt="" /> : <span className="avatar-fallback">{user.display_name.slice(0, 1)}</span>}
            <span>{user.display_name}</span>
          </Link>
          <button type="button" onClick={logout}>退出</button>
        </div>
      ) : ready ? (
        <Link href="/login" className="login-link">登录 / 注册</Link>
      ) : <span className="nav-placeholder" aria-hidden="true" />}
    </nav>
  );
}
