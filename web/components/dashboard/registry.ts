import t from "@/lib/i18n";
import type { Counts, DashboardPanelConfig, DashboardTab } from "./types";

/**
 * 工作台面板注册表。
 * 加新能力 = 新建 panel 组件文件 + 这里加一行。
 * 不动 DashboardLayout、不改路由、不改 CSS 类名。
 */
export const panelRegistry: DashboardPanelConfig[] = [
  { id: "mine",     label: t.me.tabReactions, section: "work",    href: "/aichem",                badge: (c) => c.public_reactions + c.private_reactions },
  { id: "saved",    label: t.me.tabSaved,     section: "work",    href: "/aichem?tab=saved",      badge: (c) => c.chemicals + c.reactions },
  { id: "activity", label: t.me.tabActivity,  section: "work",    href: "/aichem?tab=activity",   badge: (c) => c.unread || null },
  { id: "following", label: t.me.tabFollowing, section: "social", href: "/aichem?tab=following",  badge: (c) => c.following },
  { id: "followers", label: t.me.tabFollowers, section: "social", href: "/aichem?tab=followers",  badge: (c) => c.followers },
];

export const panelById = (id: DashboardTab): DashboardPanelConfig | undefined =>
  panelRegistry.find((p) => p.id === id);

export const sectionOrder: Array<"work" | "social" | "account"> = ["work", "social", "account"];

export const sectionLabels: Record<string, string> = {
  work: "工作",
  social: "社交",
  account: "账户",
};
