import type { Metadata } from "next";
import Link from "next/link";
import { Inter, Noto_Sans_SC } from "next/font/google";
import { AccountProvider } from "@/components/AccountContext";
import { HeaderAccount } from "@/components/HeaderAccount";
import "./globals.css";
import Script from "next/script";
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

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={`${inter.variable} ${notoSansSC.variable}`}>
      <head>
        <link rel="llms-txt" href="/llms.txt" />
        <script charSet="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js" />
        <script dangerouslySetInnerHTML={{ __html: 'LA.init({id:"1vMIAXQLAZjjdeBt",ck:"1vMIAXQLAZjjdeBt"})' }} />
      </head>
      <body>
        {/* AdSense disabled — code preserved for easy re-enabling.
            To restore: uncomment the <Script> block below and ensure ads.txt is served.
        <Script
          async
          src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2925838645350883"
          crossOrigin="anonymous"
          strategy="afterInteractive"
        />
        */}
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
          <span>{t.brand.slogan}</span>
        </footer>
      </body>
    </html>
  );
}
