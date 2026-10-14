import { SiteHeader } from "@/components/shell/SiteHeader";
import { SiteFooter } from "@/components/shell/SiteFooter";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-container">
      {/* SiteHeader 同时挂载顶栏与手机底部 tab（共用未读上下文） */}
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </div>
  );
}
