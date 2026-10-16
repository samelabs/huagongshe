import { Suspense } from "react";
import { LayoutSamplesClient } from "@/components/ui/LayoutSamples";

/**
 * /dev-ui/layout-samples —— 版式样张页（noindex，非 production 界面）。
 * 只用版式件（PageFrame/PageHead/Section/CardPanel/InfoRow/Byline）与
 * 现有原子组件组合四张页面，数据来自真实后端。定稿前不用于任何正式页面。
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
