import Link from "next/link";
import { HeaderAccount } from "@/components/HeaderAccount";
import { MobileTabBar } from "@/components/shared/MobileTabBar";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

export default async function SiteLayout({ children }: { children: React.ReactNode }) {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return (
    <div className="app-container">
      <header className="site-header">
        <div className="header-inner">
          <Link href={withLocale("/", locale)} className="brand" aria-label={t.nav.home}>
            <span className="brand-domain">huagongshe.com</span>
          </Link>
          <HeaderAccount />
        </div>
      </header>
      <main>{children}</main>
      <footer>
        <span>{t.nav.footer}：<a href="mailto:mail@huagongshe.com" className="footer-link">mail@huagongshe.com</a></span>
      </footer>
      <MobileTabBar />
    </div>
  );
}
