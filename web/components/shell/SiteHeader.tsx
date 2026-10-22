"use client";

/**
 * SiteHeader — 全站唯一顶栏（DESIGN_SYSTEM 2.3）。
 *
 * 公开页 (site) 与工作台 (workbench) 共用；外壳实例全程不卸载，工作台
 * 形态由上下文驱动（ShellWorkbenchChrome）。桌面 / 平板 / 手机三态：
 * - 桌面（≥）：标志 · 主导航（查询/Skills/MCP/工作台）·
 * 铃铛（未读红点，链接 /aichem?tab=activity）· 语言 · 头像菜单。无搜索框。
 * - 平板（641–）：主导航收进「更多」菜单。
 * - 手机（≤640）：高 --header-h-m，标志 + 汉堡抽屉 ≡ + 语言切换 ——
 * 全站一套：登录即显示汉堡（抽屉含快捷操作/语言/工作台导航/账户设置/
 * 退出登录），匿名只有标志与语言；头像菜单内容并入抽屉与底部「我的」。
 *
 * 未读数来源 = 工作台计数同一接口 /users/me/dashboard（counts.unread），
 * 不新增 API；工作台形态时初始值取外壳上下文里的 counts.unread（服务端
 * 已取，不重复请求），公开页缺省由 Provider 自取。
 * ShellUnreadContext 下发给 MobileTabBar。
 *
 * 不吸顶：header 在正常文档流中。
 */
import { Suspense } from "react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";
import { useDismissableMenu } from "@/lib/useDismissableMenu";
import type { User } from "@/lib/api";
import { HgsLogo } from "@/components/ui/HgsLogo";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { IconBell, IconChevron, IconMenu } from "@/components/ui/icons";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";
import { ShellUnreadProvider, useShellUnread } from "./ShellUnread";
import { useShellWorkbenchChrome } from "./ShellWorkbenchChrome";
import { WbMobileNav } from "@/components/workbench/WbMobileNav";
import { useToast } from "@/components/ui/Toast";
import { useLogout } from "@/components/shared/useLogout";
import { MobileTabBar } from "./MobileTabBar";

type NavItem = { href: string; label: string; match: (routePath: string) => boolean };

/** 主导航四项（首页 / Skills / MCP / 工作台），「更多」菜单与桌面导航共用 */
function useNavItems(): NavItem[] {
  const t = useDictionary();
  return [
    { href: "/", label: t.nav.tabHome, match: (p) => p === "/" || p === "" },
    { href: "/skills", label: t.nav.skills, match: (p) => p.startsWith("/skills") },
    { href: "/mcp-guide", label: t.nav.mcp, match: (p) => p.startsWith("/mcp-guide") },
    { href: "/aichem", label: t.nav.tabWorkbench, match: (p) => p === "/aichem" || p.startsWith("/aichem/") || p.startsWith("/submit") || p.startsWith("/me") },
  ];
}

export function SiteHeader() {
  const { user, ready } = useAccount();
  const t = useDictionary();
  const locale = useLocale();
  const nav = useNavItems();
  const pathname = usePathname();
  const routePath = stripLocalePrefix(pathname ?? "/");
  const chrome = useShellWorkbenchChrome();

  return (
    <ShellUnreadProvider initial={chrome?.counts?.unread ?? null}>
      <header className="sh-header">
        <div className="sh-inner">
          {/* 可访问名含可见文字「化工社」（zh lockup 有副标文本），
              纯「首页」label 会触发 axe label-content-name-mismatch */}
          <Link href={withLocale("/", locale)} className="sh-logo" aria-label={`${t.brand.name} · ${t.nav.home}`}>
            <HgsLogo variant="lockup" locale={locale} />
          </Link>

          <nav className="sh-nav" aria-label={t.nav.mainNav}>
            {nav.map((item) => (
              <Link
                key={item.href}
                href={withLocale(item.href, locale)}
                className={item.match(routePath) ? "on" : undefined}
                aria-current={item.match(routePath) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="sh-right">
            <HeaderBell user={user} />
            <MoreMenu items={nav} routePath={routePath} />
            <div className="sh-lang">
              <LanguageSwitcher />
            </div>
            {/* 账号位定宽槽（.sh-account）：宽度 = 头像菜单触发钮，内容右对齐。
                占位 / 头像菜单 / 登录按钮三种内容同槽，登录态翻转与水合翻转
                都不改变槽宽 —— 语言键位置与登录态无关 */}
            <div className="sh-account">
              {!ready ? null : user ? (
                <UserMenu user={user} />
              ) : (
                <Button variant="secondary" size="sm" className="sh-login-btn" href={withLocale("/login", locale)}>
                  {t.nav.login}
                </Button>
              )}
            </div>
          </div>

          {/* 手机（≤640）：标志 + 汉堡抽屉 + 语言切换（全站一套，不分公开/
              工作台）。登录即显示汉堡（≡，打开抽屉：快捷操作/语言/工作台
              导航/账户设置/退出登录）；匿名只有标志与语言。整页打开工作台
              时抽屉随服务端 HTML 直接输出。 */}
          <div className="sh-mobile-right">
            {!ready ? (
              /* 水合期汉堡占位：登录用户 ready 后同位替换零 pop-in；访客
                 占位消失时右侧锚定的语言键不位移 */
              <span className="sh-hydration-ph" aria-hidden="true">
                <span className="hg-btn ghost icon wb-burger"><IconMenu width={22} height={22} /></span>
              </span>
            ) : user ? (
              <Suspense>
                <WbMobileNav counts={chrome?.counts ?? null} user={user} />
              </Suspense>
            ) : null}
            <div className="sh-lang-m">
              <LanguageSwitcher />
            </div>
          </div>
        </div>
      </header>
      {/* 底部 tab 与顶栏同一未读上下文（ShellUnreadProvider 内），≤640 显示 */}
      <MobileTabBar />
    </ShellUnreadProvider>
  );
}

/* ── 桌面铃铛（ShellUnreadProvider 内消费未读数） ─────────── */
function HeaderBell({ user }: { user: User | null }) {
  const t = useDictionary();
  const locale = useLocale();
  const { ready } = useAccount();
  const unread = useShellUnread();
  // 水合期占位同形同位（语言键左侧）；ready 后访客态收敛为无
  if (!user) {
    return !ready ? (
      <span className="sh-hydration-ph" aria-hidden="true">
        <span className="hg-btn ghost icon sh-bell"><IconBell /></span>
      </span>
    ) : null;
  }
  return (
    <Link
      href={withLocale("/aichem?tab=activity", locale)}
      className="hg-btn ghost icon sh-bell"
      aria-label={unread > 0 ? t.nav.unreadCount(unread) : t.nav.notifications}
    >
      <IconBell />
      {unread > 0 && <span className="sh-bell-dot" aria-hidden="true" />}
    </Link>
  );
}

/* ── 头像菜单：我的主页 / 工作台 / 设置 / 退出 ─────────────── */
function UserMenu({ user }: { user: User }) {
  const t = useDictionary();
  const locale = useLocale();
  const menu = useDismissableMenu();
  const { open, setOpen, close } = menu;
  const logout = useLogout();

  return (
    <div className={`sh-menu${open ? " open" : ""}`} ref={menu.rootRef} onKeyDown={menu.onKeyDown}>
      <button
        ref={menu.triggerRef}
        type="button"
        className="hg-btn ghost sh-menu-trigger"
        aria-label={t.nav.openMenu}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Avatar id={user.username} name={user.display_name} src={user.avatar_url} size={32} />
        <IconChevron className="sh-chev" />
      </button>
      {open && (
        <div className="sh-menu-panel" role="menu">
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
          <Link role="menuitem" data-menu-item href={withLocale("/me/settings/api-tokens", locale)} onClick={close}>
            {t.nav.aiKey}
          </Link>
          <Link role="menuitem" data-menu-item href={withLocale("/me/settings/profile", locale)} onClick={close}>
            {t.nav.settings}
          </Link>
          <button role="menuitem" data-menu-item type="button" className="sh-menu-logout" onClick={() => { close(); void logout(); }}>
            {t.nav.logout}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── 平板「更多」菜单（641–，主导航收纳于此） ───────────── */
function MoreMenu({ items, routePath }: { items: NavItem[]; routePath: string }) {
  const t = useDictionary();
  const locale = useLocale();
  const menu = useDismissableMenu();
  const { open, setOpen, close } = menu;

  return (
    <div className={`sh-menu sh-more${open ? " open" : ""}`} ref={menu.rootRef} onKeyDown={menu.onKeyDown}>
      <button
        ref={menu.triggerRef}
        type="button"
        className="hg-btn ghost sm sh-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {t.nav.more}
        <IconChevron className="sh-chev" />
      </button>
      {open && (
        <div className="sh-menu-panel" role="menu">
          {items.map((item) => (
            <Link
              key={item.href}
              role="menuitem"
              data-menu-item
              href={withLocale(item.href, locale)}
              onClick={close}
              className={item.match(routePath) ? "on" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
