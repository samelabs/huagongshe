import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import {
  IconHome, IconNote, IconStar, IconSearch, IconCalc, IconSparkle, IconPlug,
  IconBell, IconUsers, IconUser, IconGear, GlyphRx,
} from "@/components/ui/icons";
import type { WorkbenchPanelConfig } from "./types";

/**
 * 工作台面板注册表（v1.7 Step 8 §9.4：四组 + 16px 图标）。
 * 加新能力 = 新建 panel 组件文件 + 这里加一行。
 * id 与 href 是深链/测试钉子的稳定接口，不随展示分组调整；
 * 分组（section）、图标（icon）、label 是展示层，可按 §9.4 演进。
 * 账户组只留「设置」——头像/安全/AI Key 子页在设置页内部切换
 * （api-tokens 归入工具组，作为「MCP 与 AI Key」入口）。
 */
export const workbenchRegistry: Omit<WorkbenchPanelConfig, "label">[] = [
  { id: "home",       section: "workspace", href: "/aichem",                  icon: IconHome },
  { id: "notes",      section: "workspace", href: "/aichem?tab=notes",       icon: IconNote,   badge: (c) => c.notes },
  { id: "mine",       section: "workspace", href: "/aichem?tab=mine",        icon: GlyphRx,    badge: (c) => c.public_reactions + c.private_reactions },
  { id: "saved",      section: "workspace", href: "/aichem?tab=saved",       icon: IconStar,   badge: (c) => c.chemicals + c.reactions },
  { id: "search",     section: "tools",     href: "/aichem?tab=search",      icon: IconSearch },
  { id: "stoich",     section: "tools",     href: "/aichem?tab=stoich",      icon: IconCalc },
  { id: "skills",     section: "tools",     href: "/aichem?tab=skills",      icon: IconSparkle },
  { id: "api-tokens", section: "tools",     href: "/me/settings/api-tokens", icon: IconPlug },
  { id: "activity",   section: "network",   href: "/aichem?tab=activity",    icon: IconBell,   badge: (c) => c.unread || null },
  { id: "following",  section: "network",   href: "/aichem?tab=following",   icon: IconUsers,  badge: (c) => c.following },
  { id: "followers",  section: "network",   href: "/aichem?tab=followers",   icon: IconUser,   badge: (c) => c.followers },
  { id: "profile",    section: "account",   href: "/me/settings/profile",    icon: IconGear },
];

/** panel id → 当前字典下的导航 label */
export function panelLabel(id: string, t: Dictionary): string {
  const me: Record<string, string> = {
    home: t.me.tabHome, notes: t.nav.tabNotes, search: t.me.tabSearch, stoich: t.me.tabStoich,
    mine: t.me.tabReactions, saved: t.me.tabSaved, skills: t.me.navSkills,
    "api-tokens": t.me.navMcpKey, profile: t.me.navSettings,
    activity: t.me.tabActivity, following: t.me.tabFollowing, followers: t.me.tabFollowers,
  };
  return me[id] ?? id;
}

export const sectionOrder = ["workspace", "tools", "network", "account"] as const;

export function sectionLabel(section: (typeof sectionOrder)[number], t: Dictionary): string {
  const labels: Record<string, string> = {
    workspace: t.me.sectionWorkspace,
    tools: t.me.sectionTools,
    network: t.me.sectionNetwork,
    account: t.me.sectionAccount,
  };
  return labels[section];
}
