import { SiteHeader } from "@/components/shell/SiteHeader";
import { MobileTabBar } from "@/components/shared/MobileTabBar";
import { getRequestDictionary } from "@/lib/serverI18n";

export default async function SiteLayout({ children }: { children: React.ReactNode }) {
  const t = await getRequestDictionary();
  return (
    <div className="app-container">
      {/* SiteHeader 同时挂载顶栏与手机底部 tab（共用未读上下文） */}
      <SiteHeader />
      <main>{children}</main>
      <footer>
        <span>{t.nav.footer}：<a href="mailto:mail@huagongshe.com" className="footer-link">mail@huagongshe.com</a></span>
      </footer>
      <MobileTabBar />
    </div>
  );
}
