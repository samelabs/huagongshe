"use client";

/**
 * UrlTabs — 状态存 URL 的 Tabs 包装（ui/Tabs 键盘交互 + router.push）。
 * 搜索页结果分类（?type=）等场景使用；ProfileTabs 同模式（独立实现）。
 * tabs 元素直接携带 href（纯数据），服务端组件不再向客户端组件传递函数。
 */
import { useRouter } from "next/navigation";
import { Tabs, type TabItem } from "@/components/ui/Tabs";

export type UrlTabItem = TabItem & { href?: string };

export function UrlTabs({ tabs, value, hrefFor, ariaLabel }: {
  tabs: ReadonlyArray<UrlTabItem>;
  value: string;
  hrefFor?: (id: string) => string;
  ariaLabel: string;
}) {
  const router = useRouter();
  const hrefMap = new Map(tabs.filter((t) => t.href).map((t) => [t.id, t.href as string]));

  return (
    <Tabs
      ariaLabel={ariaLabel}
      value={value}
      tabs={tabs}
      onChange={(id) => {
        const dest = hrefMap.get(id) ?? (hrefFor ? hrefFor(id) : null);
        if (dest) router.push(dest);
      }}
    />
  );
}
