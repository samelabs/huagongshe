"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import type { User } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

/**
 * 身份菜单 — 全站唯一实现，三个挂载点共用：
 * 站点 header（variant="header"）/ 工作台顶栏（"topbar"）/ 工作台抽屉头部（"drawer"）。
 *
 * 职责边界（收口规范）：
 * - 只放身份与账户级入口：公开主页 / 账户设置 / 平台管理(admin) / 退出登录
 * - 工作台功能入口（新建反应、API Token 等）不进这里，归工作台导航
 * - showWorkbenchEntry 仅站点侧为 true —— 站点页进工作台的主要通路
 * - variant 只影响触发器布局密度，菜单内容零分叉
 */
export function AccountMenu({ user, variant, showWorkbenchEntry = false }: {
  user: User;
  variant: "header" | "topbar" | "drawer";
  showWorkbenchEntry?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const menu = useRef<HTMLDetailsElement>(null);
  const { clear } = useAccount();
  const t = useDictionary();
  const locale = useLocale();

  function close() {
    if (menu.current) menu.current.open = false;
  }

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

  // 路由变化自动收起（原抽屉有此行为，站内没有 —— 统一补齐）
  useEffect(() => { close(); }, [pathname]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    close();
    clear();
    router.push("/");
    router.refresh();
  }

  return (
    <details className={`am-menu am-menu--${variant}`} ref={menu}>
      <summary aria-label={t.nav.openMenu}>
        <Avatar user={user} />
        <span className="am-name">{user.display_name}</span>
        <span className="am-chevron" aria-hidden="true" />
      </summary>
      <div className="am-dropdown">
        <div className="am-profile">
          <strong>{user.display_name}</strong>
          <span>@{user.username}</span>
        </div>
        <div className="am-links">
          {showWorkbenchEntry && <Link href={withLocale("/aichem", locale)} onClick={close}>{t.nav.workbench}</Link>}
          <Link href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)} onClick={close}>{t.nav.publicProfile}</Link>
          <Link href={withLocale("/me/settings/profile", locale)} onClick={close}>{t.nav.accountSettings}</Link>
          {user.role === "admin" && <Link href="/samelabs" onClick={close}>{t.nav.admin}</Link>}
        </div>
        <button type="button" onClick={logout}>{t.nav.logout}</button>
      </div>
    </details>
  );
}

function Avatar({ user }: { user: User }) {
  const [err, setErr] = useState(false);
  if (user.avatar_url && !err) {
    const src = user.avatar_url.endsWith(".webp")
      ? user.avatar_url.replace(".webp", "-128.webp")
      : user.avatar_url;
    return <img className="am-avatar" src={src} alt="" onError={() => setErr(true)} />;
  }
  return <span className="am-avatar am-avatar--fallback">{user.display_name.slice(0, 1)}</span>;
}
