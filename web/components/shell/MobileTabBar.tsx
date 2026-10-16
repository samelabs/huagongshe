"use client";

/**
 * MobileTabBar — 手机底部 4 tab（DESIGN_SYSTEM 2.3）。
 *
 * 首页 / · 工作台 /aichem · 动态 /aichem?tab=activity（未读徽标，
 * 未登录跳登录）· 我的（已登录弹菜单：我的主页/工作台/设置/退出；未登录跳 /login）。
 * 高度 var(--tabbar-h) + safe-area 底部内边距；当前 tab 用 var(--action)。
 * 内容区 56，safe-area 作为下方 padding，图标 20，文字和图标垂直居中。
 * 未读数来自 SiteHeader 的 ShellUnreadContext（/users/me/dashboard，同一来源）。
 * ≤640px 显示。
 */
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";
import { useShellUnread } from "./ShellUnread";
import { useToast } from "@/components/ui/Toast";
import { useDismissableMenu } from "@/lib/useDismissableMenu";
import { IconHome, IconWorkbench, IconBell, IconUser } from "@/components/ui/icons";

export function MobileTabBar() {
  const { user, clear } = useAccount();
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const unread = useShellUnread();
  const pathname = usePathname();
  const routePath = stripLocalePrefix(pathname ?? "/");
  const tabParam = useSearchParams().get("tab");
  const activityHref = user ? "/aichem?tab=activity" : "/login";
  const isActivity = routePath === "/aichem" && tabParam === "activity";
  const isWorkbench = !isActivity && (
    routePath === "/aichem" || routePath.startsWith("/aichem/")
    || routePath.startsWith("/submit") || (routePath.startsWith("/me") && !routePath.startsWith("/me/settings"))
  );
  // 底栏归属: 每个路由恰归一个 tab。
  // 查询 = 首页、搜索、化合物、反应、Skills、MCP 与指南、笔记、他人主页
  // 等公开内容页; 工作台 = /aichem 及子页、/submit、/me(设置除外);
  // 动态 = 工作台动态; 我的 = 本人主页、设置、登录与注册等账号页。
  const isAuthPage = /^\/(login|register|verify|forgot|reset|oauth)(\/|$)/.test(routePath);
  const isOwnProfile = user ? routePath === `/user/${encodeURIComponent(user.username)}` : false;
  const isMeActive = isOwnProfile || routePath.startsWith("/me/settings") || isAuthPage;
  const isHomeActive = (routePath === "/" || routePath === "")
    || (!isAuthPage && !isWorkbench && !isActivity && !isMeActive);

  const menu = useDismissableMenu();
  const { open, setOpen, close } = menu;

  async function logout() {
    setOpen(false);
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      if (!res.ok) throw new Error(`logout ${res.status}`);
    } catch {
      toast.error(t.nav.logoutFailed);
      return;
    }
    clear();
    router.push(withLocale("/", locale));
    router.refresh();
  }

  return (
    <nav className="sh-tabbar" aria-label={t.nav.bottomNav}>
      <Link
        href={withLocale("/", locale)}
        className={`sh-tab${isHomeActive ? " on" : ""}`}
        aria-current={isHomeActive ? "page" : undefined}
      >
        <IconHome />
        {t.nav.tabHome}
      </Link>
      <Link
        href={withLocale("/aichem", locale)}
        className={`sh-tab${isWorkbench ? " on" : ""}`}
        aria-current={isWorkbench ? "page" : undefined}
      >
        <IconWorkbench />
        {t.nav.tabWorkbench}
      </Link>
      <Link
        href={withLocale(activityHref, locale)}
        className={`sh-tab${isActivity ? " on" : ""}`}
        aria-current={isActivity ? "page" : undefined}
      >
        <IconBell />
        {t.nav.activity}
        {user && unread > 0 && <i className="sh-tab-badge" aria-label={t.nav.unreadCount(unread)}>{unread}</i>}
      </Link>
      {user ? (
        <div className="sh-tab-wrap" ref={menu.rootRef} onKeyDown={menu.onKeyDown}>
          <button
            ref={menu.triggerRef}
            type="button"
            className={`sh-tab${isMeActive || open ? " on" : ""}`}
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <IconUser />
            {t.nav.tabMe}
          </button>
          {open && (
            <div className="sh-tab-panel" role="menu">
              <div className="sh-menu-head">
                <strong>{user.display_name}</strong>
                <span>@{user.username}</span>
              </div>
              <Link role="menuitem" data-menu-item href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)} onClick={close}>
                {t.nav.myProfile}
              </Link>
              <Link role="menuitem" data-menu-item href={withLocale("/aichem", locale)} onClick={close}>
                {t.nav.tabWorkbench}
              </Link>
              <Link role="menuitem" data-menu-item href={withLocale("/me/settings/profile", locale)} onClick={close}>
                {t.nav.settings}
              </Link>
              <button role="menuitem" data-menu-item type="button" className="sh-menu-logout" onClick={() => void logout()}>
                {t.nav.logout}
              </button>
            </div>
          )}
        </div>
      ) : (
        <Link
          href={withLocale("/login", locale)}
          className={`sh-tab${isAuthPage ? " on" : ""}`}
          aria-current={isAuthPage ? "page" : undefined}
        >
          <IconUser />
          {t.nav.tabMe}
        </Link>
      )}
    </nav>
  );
}
