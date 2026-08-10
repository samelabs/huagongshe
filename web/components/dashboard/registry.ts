import t from "@/lib/i18n";
import type { DashboardPanelConfig } from "./types";

/**
 * 工作台面板注册表。
 * 加新能力 = 新建 panel 组件文件 + 这里加一行。
 * 不动 WorkbenchNav、不改路由、不改 CSS 类名。
 */
export const panelRegistry: DashboardPanelConfig[] = [
  { id: "mine",        label: t.me.tabReactions, section: "work",    href: "/aichem",               badge: (c) => c.public_reactions + c.private_reactions },
  { id: "saved",       label: t.me.tabSaved,     section: "work",    href: "/aichem?tab=saved",     badge: (c) => c.chemicals + c.reactions },
  { id: "activity",    label: t.me.tabActivity,  section: "work",    href: "/aichem?tab=activity",  badge: (c) => c.unread || null },
  { id: "following",   label: t.me.tabFollowing, section: "social",  href: "/aichem?tab=following", badge: (c) => c.following },
  { id: "followers",   label: t.me.tabFollowers, section: "social",  href: "/aichem?tab=followers", badge: (c) => c.followers },
  { id: "profile",     label: t.settings.nav.profile,  section: "account", href: "/me/settings/profile" },
  { id: "avatar",      label: t.settings.nav.avatar,   section: "account", href: "/me/settings/avatar" },
  { id: "security",    label: t.settings.nav.security, section: "account", href: "/me/settings/security" },
  { id: "api-tokens",  label: t.settings.nav.tokens,   section: "account", href: "/me/settings/api-tokens" },
];

export const panelById = (id: string): DashboardPanelConfig | undefined =>
  panelRegistry.find((p) => p.id === id);

export const sectionOrder: Array<DashboardPanelConfig["section"]> = ["work", "social", "account"];

export const sectionLabels: Record<DashboardPanelConfig["section"], string> = {
  work: "工作",
  social: "社交",
  account: "账户",
};
