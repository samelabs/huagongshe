import { SiteFooter } from "@/components/shell/SiteFooter";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-container">
      {/* 顶栏与手机底部 tab 由根 layout 的外壳统一挂载，路由组切换不重建 */}
      <main>{children}</main>
      <SiteFooter />
    </div>
  );
}
