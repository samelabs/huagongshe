"use client";

/**
 * UrlTabs — 状态存 URL 的 Tabs 包装（ui/Tabs 键盘交互 + router.push）。
 * 搜索页结果分类（?type=）等场景使用；ProfileTabs 同模式（独立实现）。
 */
import { useRouter } from "next/navigation";
import { Tabs, type TabItem } from "@/components/ui/Tabs";

export function UrlTabs({ tabs, value, hrefFor, ariaLabel }: {
  tabs: ReadonlyArray<TabItem>;
  value: string;
  hrefFor: (id: string) => string;
  ariaLabel: string;
}) {
  const router = useRouter();
  return (
    <Tabs
      ariaLabel={ariaLabel}
      value={value}
      tabs={tabs}
      onChange={(id) => router.push(hrefFor(id))}
    />
  );
}
