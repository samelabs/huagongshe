"use client";

/**
 * HydrationMarker — 根 layout 挂载的最小组件：挂载（即 React hydration
 * 完成、全部挂载 effect 已跑）后给 <html> 打 data-hydrated="1"。
 *
 * 动机（Step 9 Part A.1）：问候语等「SSR 不带、挂载后 effect 补」的内容，
 * 截图工具在 networkidle 即拍会截到水合前的旧 DOM（两端渲染路径不同时序
 * 的根源）。工具等待本标记即可确定性拍到最终一致的状态。SSR/水合首帧
 * 不输出该属性，不影响 hydration（属性只增不改）。
 */
import { useEffect } from "react";

export function HydrationMarker() {
  useEffect(() => {
    document.documentElement.dataset.hydrated = "1";
  }, []);
  return null;
}
