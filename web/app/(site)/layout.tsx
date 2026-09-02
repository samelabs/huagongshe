import Link from "next/link";
import { HeaderAccount } from "@/components/HeaderAccount";
import { MobileTabBar } from "@/components/shared/MobileTabBar";
import { ShellDebug } from "@/components/ShellDebug"; // 临时诊断, 定位壳层失控后删
import t from "@/lib/i18n";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-container">
      <header className="site-header">
        <div className="header-inner">
          <Link href="/" className="brand" aria-label={t.nav.home}>
            <span className="brand-domain">化工社AIchem</span>
          </Link>
          <HeaderAccount />
        </div>
      </header>
      <main>{children}</main>
      <footer>
        <span>{t.nav.footer}：<a href="mailto:mail@huagongshe.com" className="footer-link">mail@huagongshe.com</a></span>
      </footer>
      <MobileTabBar />
      <ShellDebug />
    </div>
  );
}
