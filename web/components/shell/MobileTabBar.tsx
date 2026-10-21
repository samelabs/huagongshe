"use client";

/**
 * MobileTabBar — 手机底部 4 tab（DESIGN_SYSTEM 2.3）。
 *
 * 首页 / · 工作台 /aichem · 通知 /aichem?tab=activity（未读徽标，
 * 未登录跳登录）· 我的（直接落「我的主页」/user/{username}——公开主页
 * 区分主人态/游客态，主人态承载设置入口与身份操作；未登录跳 /login）。
 * 高度 var(--tabbar-h) + safe-area 底部内边距；当前 tab 用 var(--action)。
 * 内容区 56，safe-area 作为下方 padding，图标 20，文字和图标垂直居中。
 * 未读数来自 SiteHeader 的 ShellUnreadContext（/users/me/dashboard，同一来源）。
 * ≤640px 显示。输入法弹出时整体退场、收起恢复（规范 2.3；iOS 键盘会把
 * fixed 底栏顶到键盘上方，退场由 visualViewport 判定，CSS 见 .sh-tabbar.kb）。
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";
import { useShellUnread } from "./ShellUnread";
import { IconHome, IconWorkbench, IconBell, IconUser } from "@/components/ui/icons";

export function MobileTabBar() {
  const { user } = useAccount();
  const t = useDictionary();
  const locale = useLocale();
  const unread = useShellUnread();
  const pathname = usePathname();
  const routePath = stripLocalePrefix(pathname ?? "/");
  const tabParam = useSearchParams().get("tab");
  // 键盘判定:视觉视口高度较「历史峰值」骤降 150px 以上。iOS 上
  // innerHeight 跟随视觉视口同缩(innerHeight - vv.height 恒≈0, 布局视口
  // 差值判定在 iOS 失效), 峰值差判定两端通用; 地址栏收缩幅度(<150px)
  // 不误报; 转向(宽度变化)重置基准。不支持 visualViewport 的环境保持原状。
  const [keyboardUp, setKeyboardUp] = useState(false);
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    let baselineW = vv.width;
    let peakH = vv.height;
    const sync = () => {
      if (Math.abs(vv.width - baselineW) > 1) {
        baselineW = vv.width;
        peakH = vv.height;
      }
      if (vv.height > peakH) peakH = vv.height;
      setKeyboardUp(peakH - vv.height > 150);
    };
    vv.addEventListener("resize", sync);
    vv.addEventListener("scroll", sync);
    sync();
    return () => {
      vv.removeEventListener("resize", sync);
      vv.removeEventListener("scroll", sync);
    };
  }, []);
  const activityHref = user ? "/aichem?tab=activity" : "/login";
  const isActivity = routePath === "/aichem" && tabParam === "activity";
  const isWorkbench = !isActivity && (
    routePath === "/aichem" || routePath.startsWith("/aichem/")
    || routePath.startsWith("/submit") || (routePath.startsWith("/me") && !routePath.startsWith("/me/settings"))
  );
  // 底栏归属: 每个路由恰归一个 tab。
  // 查询 = 首页、搜索、化合物、反应、Skills、MCP 与指南、笔记、他人主页
  // 等公开内容页; 工作台 = /aichem 及子页、/submit、/me(设置除外);
  // 通知 = 工作台通知面板; 我的 = 本人主页、设置、登录与注册等账号页。
  const isAuthPage = /^\/(login|register|verify|forgot|reset|oauth)(\/|$)/.test(routePath);
  const isOwnProfile = user ? routePath === `/user/${encodeURIComponent(user.username)}` : false;
  const isMeActive = isOwnProfile || routePath.startsWith("/me/settings") || isAuthPage;
  const isHomeActive = (routePath === "/" || routePath === "")
    || (!isAuthPage && !isWorkbench && !isActivity && !isMeActive);

  return (
    <nav className={keyboardUp ? "sh-tabbar sh-tabbar-kb" : "sh-tabbar"} aria-label={t.nav.bottomNav}>
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
        {t.nav.notifications}
        {user && unread > 0 && <i className="sh-tab-badge" aria-label={t.nav.unreadCount(unread)}>{unread}</i>}
      </Link>
      {user ? (
        <Link
          href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)}
          className={`sh-tab${isMeActive ? " on" : ""}`}
          aria-current={isMeActive ? "page" : undefined}
        >
          <IconUser />
          {t.nav.tabMe}
        </Link>
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
