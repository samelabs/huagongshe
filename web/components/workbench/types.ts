import type { ComponentType, SVGProps } from "react";

export type LoadState = "idle" | "loading" | "ready" | "error";
export type WorkbenchTab = "home" | "notes" | "search" | "stoich" | "mine" | "saved" | "activity" | "followers" | "following" | "skills" | "profile" | "avatar" | "security" | "api-tokens";
export type ReactionVisibility = "all" | "public" | "private";
export type SavedKind = "chemicals" | "reactions";

export type SkillItem = {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  category: string | null;
  origin: string;
  visibility: "private" | "public";
  has_scripts: boolean;
  file_count: number;
  size_bytes: number;
  updated_at: string;
  owner: { username: string; display_name: string | null };
};

export type Counts = {
  public_reactions: number;
  private_reactions: number;
  following: number;
  followers: number;
  chemicals: number;
  reactions: number;
  unread: number;
  /** 笔记总数（dashboard 不含，由 layout 用 /users/me/notes?page_size=1 的 total 补齐） */
  notes: number;
};

export type Summary = {
  username: string;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
  created_at: string;
  counts: Counts;
};

export type Reaction = {
  id: number;
  reaction_smiles: string | null;
  visibility?: "public" | "private";
  updated_at?: string;
  followers?: number;
};

export type ReactionResponse = {
  items: Reaction[];
  counts: { all: number; public: number; private: number };
  page: number;
  page_size: number;
};

export type ChemicalFollow = {
  id: number;
  preferred_name: string | null;
  iupac_name: string | null;
  name_cn: string | null;
  molecular_formula: string | null;
  smiles: string | null;
};

export type PageResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};


export type { NoteItem, NoteResponse, NoteVisibility } from "@/lib/api";

export type Notice = {
  id: number;
  event_type: "new_reaction";
  reaction_id: number;
  chemical_id: number | null;
  actor_username: string;
  actor_display_name: string | null;
  created_at: string;
  read_at: string | null;
};

export type NoticeResponse = {
  items: Notice[];
  total: number;
  page: number;
  page_size: number;
};

/* ── Panel 注册接口 ───────────────────────────────────
 * 加新能力 = 新建 panel 组件 + registry.ts 加一行。
 * 不改 WorkbenchNav、不改路由、不改 CSS 类名。
 * Step 8 §9.4：分组收敛为 workspace/tools/network/account 四组，
 * 每项带 16px 图标（icon）。
 */
export type PanelSection = "workspace" | "tools" | "network" | "account";

/** 侧栏图标组件（24 视口 stroke 图标，CSS 按 16px 渲染） */
export type PanelIcon = ComponentType<SVGProps<SVGSVGElement>>;

/** 每个面板自治：自己 fetch 数据，自己管理三态 */
export interface PanelProps {
  page: number;
}

export interface WorkbenchPanelConfig {
  id: WorkbenchTab;
  label: string;
  section: PanelSection;
  href: string;
  /** 侧栏/抽屉 16px 图标 */
  icon?: PanelIcon;
  badge?: (counts: Counts) => number | null;
}
