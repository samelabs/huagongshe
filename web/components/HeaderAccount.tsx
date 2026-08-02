"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/AccountContext";
import type { User } from "@/lib/api";
import t from "@/lib/i18n";

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
    <nav aria-label={t.nav.mainNav}>
      <Link href="/guide" className="nav-guide" aria-label={t.nav.guide}>
        <span className="guide-full">{t.nav.guide}</span><span className="guide-short">AI</span>
      </Link>
      {user ? (
        <>
          <details className="account-menu" ref={menu}>
            <summary aria-label={t.nav.openMenu}>
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
                <Link href="/me" onClick={closeMenu}>{t.nav.knowledgeBase}</Link>
                <Link href="/submit" onClick={closeMenu}>{t.nav.newReaction}</Link>
                <Link href="/me/settings/api-tokens" onClick={closeMenu}>{t.nav.aiAssistant}</Link>
                <Link href={`/user/${encodeURIComponent(user.username)}`} onClick={closeMenu}>{t.nav.publicProfile}</Link>
                <Link href="/me/settings/profile" onClick={closeMenu}>{t.nav.accountSettings}</Link>
                {user.role === "admin" && <Link href="/samelabs" onClick={closeMenu}>{t.nav.admin}</Link>}
              </div>
              <button type="button" onClick={logout}>{t.nav.logout}</button>
            </div>
          </details>
        </>
      ) : ready ? (
        <Link href="/login" className="login-link">{t.nav.login}</Link>
      ) : <span className="nav-placeholder" aria-hidden="true" />}
    </nav>
  );
}

function Avatar({ user }: { user: User }) {
  const [err, setErr] = useState(false);
  if (user.avatar_url && !err) {
    return <img className="header-avatar" src={user.avatar_url.replace(".webp", "-128.webp")} alt="" onError={() => setErr(true)} />;
  }
  return <span className="avatar-fallback">{user.display_name.slice(0, 1)}</span>;
}
