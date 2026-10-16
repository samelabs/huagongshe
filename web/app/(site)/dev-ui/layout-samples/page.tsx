import { Suspense } from "react";
import { LayoutSamplesClient } from "@/components/ui/LayoutSamples";
import "../dev-ui.css";

/**
 * /dev-ui/layout-samples —— 版式基准预览页（noindex，非 production 界面）。
 * 只用版式件（PageFrame/PageHead/Section/CardPanel/InfoRow/Byline）与
 * 现有原子组件组合四张页面，数据来自真实后端。基准未经确认前不用于任何正式页面。
 */
export const metadata = {
  robots: { index: false, follow: false },
};

export default function LayoutSamplesPage() {
  return (
    <Suspense>
      <LayoutSamplesClient />
    </Suspense>
  );
}
