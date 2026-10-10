"use client";

/**
 * SiteHeader — v1.7 全站唯一顶栏（DESIGN_SYSTEM §8，参考 §8–11 模板）。
 *
 * 公开页 (site) 与工作台 (workbench) 两个 layout 共用；桌面 / 平板 / 手机三态：
 * - 桌面（>1024）：标志 · 主导航（查询/Skills/MCP/工作台）· 全局搜索（⌘K）·
 *   铃铛（未读红点，链接 /aichem?tab=activity）· 语言 · 头像菜单。
 * - 平板（641–1024）：主导航收进「更多」菜单，搜索框缩短。
 * - 手机（≤640）：高 --header-h-m，标志（24，无中文副标，由全局 .hgs-logo 媒体
 *   规则处理）+ 搜索图标（跳 /search?focus=1 自动聚焦）+ 头像/登录 +
 *   mobileActions 插槽（工作台传入抽屉汉堡按钮）。
 *
 * 未读数来源 = 工作台计数同一接口 /users/me/dashboard（counts.unread），
 * 只在已登录时请求，不新增 API；工作台 layout 通过 initialUnread 直传
 * 服务端已取的值，避免重复请求。ShellUnreadContext 下发给 MobileTabBar。
 *
 * 不吸顶（保持 v1.6 锚点修复）：header 在正常文档流中。
 */
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";
import type { User } from "@/lib/api";
import { HgsLogo } from "@/components/ui/HgsLogo";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { IconSearch, IconBell, IconChevron } from "@/components/ui/icons";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";
import { ShellUnreadProvider, useShellUnread } from "./ShellUnread";
import { MobileTabBar } from "./MobileTabBar";

type NavItem = { href: string; label: string; match: (routePath: string) => boolean };

/** 主导航四项（查询 / Skills / MCP / 工作台），「更多」菜单与桌面导航共用 */
function useNavItems(): NavItem[] {
  const t = useDictionary();
  return [
    { href: "/search", label: t.nav.tabQuery, match: (p) => p === "/search" || p.startsWith("/search/") },
    { href: "/skills", label: t.nav.skills, match: (p) => p.startsWith("/skills") },
    { href: "/mcp-guide", label: t.nav.mcp, match: (p) => p.startsWith("/mcp-guide") },
    { href: "/aichem", label: t.nav.tabWorkbench, match: (p) => p === "/aichem" || p.startsWith("/aichem/") || p.startsWith("/submit") || p.startsWith("/me") },
  ];
}

export function SiteHeader({ initialUnread, mobileActions }: {
  /** 工作台 layout 传入服务端已取的 counts.unread；公开页缺省由 Provider 自取 */
  initialUnread?: number;
  /** 手机端右侧插槽（工作台传抽屉汉堡按钮） */
  mobileActions?: React.ReactNode;
}) {
  const { user } = useAccount();
  const t = useDictionary();
  const locale = useLocale();
  const unread = useShellUnread();
  const nav = useNavItems();
  const pathname = usePathname();
  const routePath = stripLocalePrefix(pathname ?? "/");

  return (
    <ShellUnreadProvider initial={initialUnread}>
      <header className="sh-header">
        <div className="sh-inner">
          <Link href={withLocale("/", locale)} className="sh-logo" aria-label={t.nav.home}>
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

          <HeaderSearch />

          <div className="sh-right">
            {user && (
              <Link
                href={withLocale("/aichem?tab=activity", locale)}
                className="hg-btn ghost icon sh-bell"
                aria-label={unread > 0 ? t.nav.unreadCount(unread) : t.nav.activity}
              >
                <IconBell />
                {unread > 0 && <span className="sh-bell-dot" aria-hidden="true" />}
              </Link>
            )}
            <MoreMenu items={nav} routePath={routePath} />
            <div className="sh-lang">
              <LanguageSwitcher />
            </div>
            {user ? (
              <UserMenu user={user} />
            ) : (
              <Button variant="secondary" size="sm" className="sh-login-btn" href={withLocale("/login", locale)}>
                {t.nav.login}
              </Button>
            )}
          </div>

          {/* 手机（≤640）：搜索图标 + 头像/登录 + 工作台抽屉汉堡 */}
          <div className="sh-mobile-right">
            <Link
              href={withLocale("/search?focus=1", locale)}
              className="hg-btn ghost icon"
              aria-label={t.nav.searchAria}
            >
              <IconSearch />
            </Link>
            {user ? (
              <UserMenu user={user} />
            ) : (
              <Link href={withLocale("/login", locale)} className="sh-login-sm">{t.nav.loginShort}</Link>
            )}
            {mobileActions}
          </div>
        </div>
      </header>
      {/* 底部 tab 与顶栏同一未读上下文（ShellUnreadProvider 内），≤640 显示 */}
      <MobileTabBar />
    </ShellUnreadProvider>
  );
}

/* ── 全局搜索框（⌘K / Ctrl+K / / 聚焦；回车跳 /search?q=） ── */
function HeaderSearch() {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        return;
      }
      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const el = e.target instanceof HTMLElement ? e.target : null;
        const editable = el != null && (
          el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT"
          || el.isContentEditable
        );
        if (!editable) {
          e.preventDefault();
          inputRef.current?.focus();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form
      className="sh-search"
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        const value = query.trim();
        if (!value) { inputRef.current?.focus(); return; }
        router.push(withLocale(`/search?q=${encodeURIComponent(value)}`, locale));
      }}
    >
      <IconSearch className="sh-search-icon" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t.nav.globalSearch}
        aria-label={t.nav.searchAria}
        autoComplete="off"
        spellCheck={false}
        maxLength={4000}
        enterKeyHint="search"
      />
      <kbd aria-hidden="true">⌘K</kbd>
    </form>
  );
}

/* ── 下拉菜单基座：Esc 关闭 + 焦点回触发器 + 方向键移动 + 外点关闭 ── */
function useMenuKeyboard(open: boolean, onClose: () => void, panelRef: React.RefObject<HTMLElement | null>, triggerRef: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      const inPanel = panelRef.current?.contains(e.target as Node);
      const inTrigger = triggerRef.current?.contains(e.target as Node);
      if (!inPanel && !inTrigger) onClose();
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, onClose, panelRef, triggerRef]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      triggerRef.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const panel = panelRef.current;
    if (!panel) return;
    const items = Array.from(panel.querySelectorAll<HTMLElement>("[data-sh-menu-item]"))
      .filter((el) => el.offsetParent !== null);
    if (items.length === 0) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "ArrowDown"
      ? items[(index + 1 + items.length) % items.length]
      : items[(index - 1 + items.length) % items.length];
    next.focus();
  }, [open, onClose, panelRef, triggerRef]);

  return onKeyDown;
}

/* ── 头像菜单：我的主页 / 工作台 / 设置 / 退出 ─────────────── */
function UserMenu({ user }: { user: User }) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const { clear } = useAccount();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // 路由变化自动收起
  useEffect(() => { setOpen(false); }, [pathname]);

  const close = useCallback(() => setOpen(false), []);
  const onKeyDown = useMenuKeyboard(open, close, panelRef, triggerRef);

  async function logout() {
    setOpen(false);
    await fetch("/api/auth/logout", { method: "POST" });
    clear();
    router.push(withLocale("/", locale));
    router.refresh();
  }

  return (
    <div className={`sh-menu${open ? " open" : ""}`} onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className="hg-btn ghost sh-menu-trigger"
        aria-label={t.nav.openMenu}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Avatar id={user.id} name={user.display_name} src={user.avatar_url} size={32} />
        <IconChevron className="sh-chev" />
      </button>
      {open && (
        <div ref={panelRef} className="sh-menu-panel" role="menu">
          <div className="sh-menu-head">
            <strong>{user.display_name}</strong>
            <span>@{user.username}</span>
          </div>
          <Link role="menuitem" data-sh-menu-item href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)} onClick={close}>
            {t.nav.myProfile}
          </Link>
          <Link role="menuitem" data-sh-menu-item href={withLocale("/aichem", locale)} onClick={close}>
            {t.nav.tabWorkbench}
          </Link>
          <Link role="menuitem" data-sh-menu-item href={withLocale("/me/settings/profile", locale)} onClick={close}>
            {t.nav.settings}
          </Link>
          <button role="menuitem" data-sh-menu-item type="button" className="sh-menu-logout" onClick={() => void logout()}>
            {t.nav.logout}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── 平板「更多」菜单（641–1024，主导航收纳于此） ───────────── */
function MoreMenu({ items, routePath }: { items: NavItem[]; routePath: string }) {
  const t = useDictionary();
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => { setOpen(false); }, [pathname]);

  const close = useCallback(() => setOpen(false), []);
  const onKeyDown = useMenuKeyboard(open, close, panelRef, triggerRef);

  return (
    <div className={`sh-menu sh-more${open ? " open" : ""}`} onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
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
        <div ref={panelRef} className="sh-menu-panel" role="menu">
          {items.map((item) => (
            <Link
              key={item.href}
              role="menuitem"
              data-sh-menu-item
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
