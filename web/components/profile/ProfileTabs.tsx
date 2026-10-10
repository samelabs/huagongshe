"use client";

/**
 * ProfileTabs — 公开主页 反应/笔记 Tabs（Step 10 §9.5）。
 * 状态存 URL ?tab=（reactions|notes），方便分享与刷新保持；服务端按 tab
 * 渲染对应列表。键盘交互由 ui/Tabs 提供。
 */
import { useRouter } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Tabs } from "@/components/ui/Tabs";

export function ProfileTabs({ username, tab, reactionCount, noteCount }: {
  username: string;
  tab: "reactions" | "notes";
  reactionCount: number;
  /** 笔记区块加载失败时未知 → 不显示计数 */
  noteCount?: number;
}) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const base = `/user/${encodeURIComponent(username)}`;
  return (
    <Tabs
      ariaLabel={t.user.profileTabsLabel}
      value={tab}
      onChange={(id) => router.push(withLocale(id === "notes" ? `${base}?tab=notes` : `${base}?tab=reactions`, locale))}
      tabs={[
        { id: "reactions", label: t.user.tabReactions, count: reactionCount },
        { id: "notes", label: t.user.tabNotes, count: noteCount },
      ]}
    />
  );
}
