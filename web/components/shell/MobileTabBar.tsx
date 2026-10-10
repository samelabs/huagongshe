"use client";

/**
 * MobileTabBar — 手机底部 4 tab（DESIGN_SYSTEM §8/§9.7，参考 §12 .m-tab）。
 *
 * 查询 /search · 工作台 /aichem · 动态 /aichem?tab=activity（未读徽标，
 * 未登录跳登录）· 我的（已登录 /user/<自己>，未登录 /login）。
 * 高度 var(--tabbar-h) + safe-area 底部内边距；当前 tab 用 var(--action)。
 * 未读数来自 SiteHeader 的 ShellUnreadContext（/users/me/dashboard，同一来源）。
 * ≤640px 显示；页面内容让位由各布局的 padding-bottom 处理。
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";
import { useShellUnread } from "./ShellUnread";
import { IconSearch, IconHome, IconBell, IconUser } from "@/components/ui/icons";

export function MobileTabBar() {
  const { user } = useAccount();
  const t = useDictionary();
  const locale = useLocale();
  const unread = useShellUnread();
  const routePath = stripLocalePrefix(usePathname() ?? "/");
  const activityHref = user ? "/aichem?tab=activity" : "/login";
  const meHref = user ? `/user/${encodeURIComponent(user.username)}` : "/login";
  const isActivity = routePath === "/aichem" && useSearchParams().get("tab") === "activity";
  const isWorkbench = !isActivity && (
    routePath === "/aichem" || routePath.startsWith("/aichem/")
    || routePath.startsWith("/submit") || routePath.startsWith("/me")
  );

  return (
    <nav className="sh-tabbar" aria-label={t.nav.bottomNav}>
      <Link
        href={withLocale("/search", locale)}
        className={`sh-tab${routePath === "/search" || routePath.startsWith("/search/") ? " on" : ""}`}
        aria-current={routePath === "/search" || routePath.startsWith("/search/") ? "page" : undefined}
      >
        <IconSearch />
        {t.nav.tabQuery}
      </Link>
      <Link
        href={withLocale("/aichem", locale)}
        className={`sh-tab${isWorkbench ? " on" : ""}`}
        aria-current={isWorkbench ? "page" : undefined}
      >
        <IconHome />
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
      <Link
        href={withLocale(meHref, locale)}
        className={`sh-tab${routePath.startsWith("/user/") ? " on" : ""}`}
        aria-current={routePath.startsWith("/user/") ? "page" : undefined}
      >
        <IconUser />
        {t.nav.tabMe}
      </Link>
    </nav>
  );
}
