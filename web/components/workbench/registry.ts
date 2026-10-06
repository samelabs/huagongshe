import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import type { WorkbenchPanelConfig } from "./types";

/**
 * 工作台面板注册表。
 * 加新能力 = 新建 panel 组件文件 + 这里加一行。
 * 不动 WorkbenchNav、不改路由、不改 CSS 类名。
 * label 不再模块级固定(原依赖静态 zh 字典), 改为 id → 当前请求字典的解析函数。
 */
export const workbenchRegistry: Omit<WorkbenchPanelConfig, "label">[] = [
  { id: "home",        section: "workspace", href: "/aichem" },
  { id: "notes",       section: "workspace", href: "/aichem?tab=notes" },
  { id: "mine",        section: "workspace", href: "/aichem?tab=mine",      badge: (c) => c.public_reactions + c.private_reactions },
  { id: "saved",       section: "workspace", href: "/aichem?tab=saved",     badge: (c) => c.chemicals + c.reactions },
  { id: "search",      section: "tools",     href: "/aichem?tab=search" },
  { id: "stoich",      section: "tools",     href: "/aichem?tab=stoich" },
  { id: "skills",      section: "agent",     href: "/aichem?tab=skills" },
  { id: "activity",    section: "network",   href: "/aichem?tab=activity",  badge: (c) => c.unread || null },
  { id: "following",   section: "network",   href: "/aichem?tab=following", badge: (c) => c.following },
  { id: "followers",   section: "network",   href: "/aichem?tab=followers", badge: (c) => c.followers },
  { id: "profile",     section: "account",   href: "/me/settings/profile" },
  { id: "avatar",      section: "account",   href: "/me/settings/avatar" },
  { id: "security",    section: "account",   href: "/me/settings/security" },
  { id: "api-tokens",  section: "account",   href: "/me/settings/api-tokens" },
];

/** panel id → 当前字典下的导航 label */
export function panelLabel(id: string, t: Dictionary): string {
  const me: Record<string, string> = {
    home: t.me.tabHome, notes: t.me.tabNotes, search: t.me.tabSearch, stoich: t.me.tabStoich,
    mine: t.me.tabReactions, saved: t.me.tabSaved, skills: t.me.tabSkills,
    activity: t.me.tabActivity, following: t.me.tabFollowing, followers: t.me.tabFollowers,
  };
  const settings: Record<string, string> = {
    profile: t.settings.nav.profile, avatar: t.settings.nav.avatar,
    security: t.settings.nav.security, "api-tokens": t.settings.nav.tokens,
  };
  return me[id] ?? settings[id] ?? id;
}

export const sectionOrder = ["workspace", "tools", "agent", "network", "account"] as const;

export function sectionLabel(section: (typeof sectionOrder)[number], t: Dictionary): string {
  const labels: Record<string, string> = {
    workspace: t.me.sectionWorkspace,
    tools: t.me.sectionTools,
    agent: t.me.sectionAgent,
    network: t.me.sectionNetwork,
    account: t.me.sectionAccount,
  };
  return labels[section];
}
