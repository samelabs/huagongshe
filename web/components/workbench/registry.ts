import t from "@/lib/i18n";
import type { WorkbenchPanelConfig } from "./types";

/**
 * 工作台面板注册表。
 * 加新能力 = 新建 panel 组件文件 + 这里加一行。
 * 不动 WorkbenchNav、不改路由、不改 CSS 类名。
 */
export const workbenchRegistry: WorkbenchPanelConfig[] = [
  { id: "home",        label: t.me.tabHome,      section: "work",    href: "/aichem" },
  { id: "search",      label: t.me.tabSearch,    section: "work",    href: "/aichem?tab=search" },
  { id: "mine",        label: t.me.tabReactions, section: "work",    href: "/aichem?tab=mine",      badge: (c) => c.public_reactions + c.private_reactions },
  { id: "saved",       label: t.me.tabSaved,     section: "work",    href: "/aichem?tab=saved",     badge: (c) => c.chemicals + c.reactions },
  { id: "activity",    label: t.me.tabActivity,  section: "work",    href: "/aichem?tab=activity",  badge: (c) => c.unread || null },
  { id: "following",   label: t.me.tabFollowing, section: "social",  href: "/aichem?tab=following", badge: (c) => c.following },
  { id: "followers",   label: t.me.tabFollowers, section: "social",  href: "/aichem?tab=followers", badge: (c) => c.followers },
  { id: "profile",     label: t.settings.nav.profile,  section: "account", href: "/me/settings/profile" },
  { id: "avatar",      label: t.settings.nav.avatar,   section: "account", href: "/me/settings/avatar" },
  { id: "security",    label: t.settings.nav.security, section: "account", href: "/me/settings/security" },
  { id: "api-tokens",  label: t.settings.nav.tokens,   section: "account", href: "/me/settings/api-tokens" },
];

export const sectionOrder: Array<WorkbenchPanelConfig["section"]> = ["work", "social", "account"];

export const sectionLabels: Record<WorkbenchPanelConfig["section"], string> = {
  work: t.me.sectionWork,
  social: t.me.sectionSocial,
  account: t.me.sectionAccount,
};
