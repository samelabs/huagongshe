"use client";

/**
 * ProfileTabs — 公开主页 笔记/反应 Tabs（DESIGN_SYSTEM 6.6）。
 * 状态存 URL ?tab=（notes|reactions），方便分享与刷新保持；服务端按 tab
 * 渲染对应列表。笔记是社交承载，排在反应之前；手机（≤640）默认落笔记
 * tab —— 主页匿名走边缘缓存，默认值不能按 UA 在服务端分叉，由本组件
 * 挂载后归位（仅 URL 未显式带 tab 时 replace 一次，不写返回历史）。
 * 键盘交互由 ui/Tabs 提供。
 */
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
  const searchParams = useSearchParams();
  const t = useDictionary();
  const locale = useLocale();
  const base = `/user/${encodeURIComponent(username)}`;
  useEffect(() => {
    if (searchParams.get("tab")) return;
    if (window.matchMedia("(max-width: 640px)").matches) {
      router.replace(withLocale(`${base}?tab=notes`, locale));
    }
  }, [searchParams, router, base, locale]);
  return (
    <Tabs
      ariaLabel={t.user.profileTabsLabel}
      value={tab}
      onChange={(id) => router.push(withLocale(id === "notes" ? `${base}?tab=notes` : `${base}?tab=reactions`, locale))}
      tabs={[
        { id: "notes", label: t.user.tabNotes, count: noteCount },
        { id: "reactions", label: t.user.tabReactions, count: reactionCount },
      ]}
    />
  );
}
