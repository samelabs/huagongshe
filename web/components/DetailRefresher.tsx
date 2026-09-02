"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * DetailRefresher(0902 P1): 详情页在途数据自动刷新。
 *
 * PB(enrichment.status==='queued')或 CB(externals state 待定但页面缺数据)在途时,
 * 每 4s router.refresh() 重走 SSR 拿新数据; 数据到/90s 超时停。
 * 只在服务端判定"在途"时渲染, 静态页零开销。
 */
export function DetailRefresher({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started > 90_000) {
        clearInterval(timer); // 超时停: 留现有"稍后再看"文案
        return;
      }
      router.refresh();
    }, 4_000);
    return () => clearInterval(timer);
  }, [active, router]);
  return null;
}
