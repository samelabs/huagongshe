"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/AccountContext";
import type { User } from "@/lib/api";

export function HeaderAccount() {
  const router = useRouter();
  const menu = useRef<HTMLDetailsElement>(null);
  const { user, ready, clear } = useAccount();

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
    clear();
    router.push("/");
    router.refresh();
  }

  return (
    <nav aria-label="主导航">
      <Link href="/guide" className="nav-guide"><span className="guide-full">帮助指南</span><span className="guide-short">指南</span></Link>
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
              <Link href="/me/settings/profile" onClick={closeMenu}>账户设置</Link>
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
