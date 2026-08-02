import type { Metadata } from "next";
import Link from "next/link";
import { Inter, Noto_Sans_SC } from "next/font/google";
import { AccountProvider } from "@/components/AccountContext";
import { HeaderAccount } from "@/components/HeaderAccount";
import { apiGet } from "@/lib/api";
import "./globals.css";
import t from "@/lib/i18n";

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-inter",
});

const notoSansSC = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
  variable: "--font-noto-sc",
  preload: true,
});
export const metadata: Metadata = {
  metadataBase: new URL("https://huagongshe.com"),
  title: { default: t.brand.seoTitle, template: `%s｜${t.brand.name}` },
  description: t.brand.seoDesc,
  keywords: [...t.brand.keywords, "AI Chemistry Workspace", "Chemical Knowledge Base", "Reaction Library"],
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    title: t.brand.seoTitle,
    description: t.brand.seoDesc,
    url: "/",
    siteName: t.brand.name,
    locale: "zh_CN",
    type: "website",
    images: [{ url: "/logo.png", width: 512, height: 512, alt: t.brand.ogAlt }],
  },
  twitter: { card: "summary", title: t.brand.seoTitle, description: t.brand.seoDescShort, images: ["/logo.png"] },
};

type SiteConfig = {
  analytics?: { scripts?: { provider?: string; enabled?: boolean; id?: string } };
  ads?: { adsense?: { enabled?: boolean; client?: string } };
  branding?: { slogan?: { footer?: string } };
};

export const revalidate = 300;

async function getSiteConfig(): Promise<SiteConfig> {
  try { return await apiGet<SiteConfig>("/config", 300); }
  catch { return {}; }
}

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const config = await getSiteConfig();
  const analytics = config.analytics?.scripts;
  const adsense = config.ads?.adsense;
  const footerSlogan = config.branding?.slogan?.footer || t.brand.slogan;

  return (
    <html lang="zh-CN" className={`${inter.variable} ${notoSansSC.variable}`}>
      <head>
        <link rel="llms-txt" href="/llms.txt" />
        {analytics?.enabled && analytics.id && analytics.provider === "51la" && (
          <>
            <script charSet="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js" />
            <script dangerouslySetInnerHTML={{ __html: `LA.init({id:"${analytics.id}",ck:"${analytics.id}"})` }} />
          </>
        )}
        {adsense?.enabled && adsense.client && (
          <script async src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${adsense.client}`} crossOrigin="anonymous" />
        )}
      </head>
      <body>
        <AccountProvider>
          <header className="site-header">
            <div className="header-inner">
              <Link href="/" className="brand" aria-label={t.nav.home}>
                <span className="brand-domain">
                  <span>huagongshe</span>
                  <span className="brand-dot">.</span>
                  <span>com</span>
                </span>
              </Link>
              <HeaderAccount />
            </div>
          </header>
          <main>{children}</main>
        </AccountProvider>
        <footer>
          <span>{footerSlogan}</span>
        </footer>
      </body>
    </html>
  );
}
