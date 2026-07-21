"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type User = {
  id: number;
  username: string;
  display_name: string;
  email: string;
  avatar_url: string | null;
  role: "member" | "admin";
};

export function HeaderAccount() {
  const router = useRouter();
  const menu = useRef<HTMLDetailsElement>(null);
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

  useEffect(() => {
    function closeOnOutside(event: PointerEvent) {
      if (menu.current?.open && !menu.current.contains(event.target as Node)) menu.current.open = false;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && menu.current?.open) {
        menu.current.open = false;
        menu.current.querySelector("summary")?.focus();
      }
    }
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  function closeMenu() {
    if (menu.current) menu.current.open = false;
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    closeMenu();
    setUser(null);
    router.push("/");
    router.refresh();
  }

  return (
    <nav aria-label="主导航">
      <Link href="/submit" className="nav-contribute"><span aria-hidden="true">＋</span>发布反应</Link>
      {user ? (
        <details className="account-menu" ref={menu}>
          <summary aria-label="打开用户菜单">
            <Avatar user={user} />
            <span className="account-name">{user.display_name}</span>
            <span className="account-chevron" aria-hidden="true" />
          </summary>
          <div className="account-dropdown">
            <div className="account-menu-profile">
              <strong>{user.display_name}</strong>
              <span>@{user.username}</span>
            </div>
            <div className="account-menu-links">
              <Link href="/me" onClick={closeMenu}>我的主页</Link>
              <Link href={`/user/${encodeURIComponent(user.username)}`} onClick={closeMenu}>公开主页</Link>
              <Link href="/me/settings" onClick={closeMenu}>账号与 Agent</Link>
              {user.role === "admin" && <Link href="/admin" onClick={closeMenu}>平台管理</Link>}
            </div>
            <button type="button" onClick={logout}>退出登录</button>
          </div>
        </details>
      ) : ready ? (
        <Link href="/login" className="login-link">登录 / 注册</Link>
      ) : <span className="nav-placeholder" aria-hidden="true" />}
    </nav>
  );
}

function Avatar({ user }: { user: User }) {
  return user.avatar_url
    ? <img className="header-avatar" src={user.avatar_url.replace(".webp", "-128.webp")} alt="" />
    : <span className="avatar-fallback">{user.display_name.slice(0, 1)}</span>;
}
