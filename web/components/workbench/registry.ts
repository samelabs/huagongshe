import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import type { WorkbenchPanelConfig } from "./types";

/**
 * 工作台面板注册表。
 * 加新能力 = 新建 panel 组件文件 + 这里加一行。
 * 不动 WorkbenchNav、不改路由、不改 CSS 类名。
 * label 不再模块级固定(原依赖静态 zh 字典), 改为 id → 当前请求字典的解析函数。
 */
export const workbenchRegistry: Omit<WorkbenchPanelConfig, "label">[] = [
  { id: "home",        section: "work",    href: "/aichem" },
  { id: "search",      section: "work",    href: "/aichem?tab=search" },
  { id: "stoich",      section: "work",    href: "/aichem?tab=stoich" },
  { id: "mine",        section: "work",    href: "/aichem?tab=mine",      badge: (c) => c.public_reactions + c.private_reactions },
  { id: "saved",       section: "work",    href: "/aichem?tab=saved",     badge: (c) => c.chemicals + c.reactions },
  { id: "skills",      section: "work",    href: "/aichem?tab=skills" },
  { id: "activity",    section: "work",    href: "/aichem?tab=activity",  badge: (c) => c.unread || null },
  { id: "following",   section: "social",  href: "/aichem?tab=following", badge: (c) => c.following },
  { id: "followers",   section: "social",  href: "/aichem?tab=followers", badge: (c) => c.followers },
  { id: "profile",     section: "account", href: "/me/settings/profile" },
  { id: "avatar",      section: "account", href: "/me/settings/avatar" },
  { id: "security",    section: "account", href: "/me/settings/security" },
  { id: "api-tokens",  section: "account", href: "/me/settings/api-tokens" },
];

/** panel id → 当前字典下的导航 label */
export function panelLabel(id: string, t: Dictionary): string {
  const me: Record<string, string> = {
    home: t.me.tabHome, search: t.me.tabSearch, stoich: t.me.tabStoich,
    mine: t.me.tabReactions, saved: t.me.tabSaved, skills: t.me.tabSkills,
    activity: t.me.tabActivity, following: t.me.tabFollowing, followers: t.me.tabFollowers,
  };
  const settings: Record<string, string> = {
    profile: t.settings.nav.profile, avatar: t.settings.nav.avatar,
    security: t.settings.nav.security, "api-tokens": t.settings.nav.tokens,
  };
  return me[id] ?? settings[id] ?? id;
}

export const sectionOrder = ["work", "social", "account"] as const;

export function sectionLabel(section: (typeof sectionOrder)[number], t: Dictionary): string {
  const labels: Record<string, string> = {
    work: t.me.sectionWork, social: t.me.sectionSocial, account: t.me.sectionAccount,
  };
  return labels[section];
}
