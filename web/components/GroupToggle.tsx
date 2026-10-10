"use client";

/**
 * GroupToggle — 组级折叠的展开/收起按钮（v1.7 Step 7 §9.1 篇幅收敛）。
 *
 * 约定：组内第 `limit` 项之后的服务端渲染元素带 `data-overflow` 且
 * `hidden`（DOM 保留——SEO 与页内搜索可用）。本组件只翻转这些元素的
 * hidden 并切换 aria-expanded / 按钮文案；文案由服务端按当前字典与
 * 计数传入（items / suppliers / tags 三种口径）。
 */
import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";

export function GroupToggle({ controls, total, collapsedLabel, expandedLabel }: {
  /** 组内容容器 id（aria-controls 指向；翻转范围 = 该容器内 [data-overflow]） */
  controls: string;
  /** 组内总项数（仅语义，供 AT） */
  total: number;
  /** 收起态文案（如「展开全部 13 项」/「查看全部 100 家」） */
  collapsedLabel: string;
  /** 展开态文案（如「收起」） */
  expandedLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="chem-group-toggle"
      aria-expanded={open}
      aria-controls={controls}
      onClick={() => {
        const next = !open;
        const root = document.getElementById(controls);
        root?.querySelectorAll<HTMLElement>("[data-overflow]").forEach((el) => { el.hidden = !next; });
        setOpen(next);
      }}
    >
      <span id={labelId}>{open ? expandedLabel : collapsedLabel}</span>
      <span className="hg-sr" aria-live="polite">{open ? expandedLabel : `${collapsedLabel} / ${total}`}</span>
    </Button>
  );
}
