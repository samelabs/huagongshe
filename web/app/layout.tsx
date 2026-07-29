import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Inter, Noto_Sans_SC } from "next/font/google";
import { AccountProvider } from "@/components/AccountContext";
import { HeaderAccount } from "@/components/HeaderAccount";
import "./globals.css";
import Script from "next/script";

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
  title: { default: "化工社｜AIchem 化学开放数据与反应记录", template: "%s｜化工社" },
  description: "AIchem 开放化学数据平台 — 查询 1.24 亿化合物与 243 万化学反应。支持 SMILES 结构搜索、CAS 号查询、反应记录管理，AI 就绪接口免费开放。",
  keywords: ["AIchem", "化学数据库", "化合物检索", "化学反应", "SMILES", "CAS号查询", "InChIKey", "结构搜索", "PubChem", "开放化学数据", "化学 AI", "RDKit"],
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "化工社｜AIchem 化学开放数据平台",
    description: "AIchem 开放化学数据 — 1.24 亿化合物、243 万反应，SMILES 结构搜索、CAS 查询、反应记录，AI 就绪接口。",
    url: "/",
    siteName: "化工社",
    locale: "zh_CN",
    type: "website",
    images: [{ url: "/logo.png", width: 512, height: 512, alt: "化工社 AIchem" }],
  },
  twitter: { card: "summary", title: "化工社 AIchem", description: "AIchem 开放化学数据 — 1.24 亿化合物，243 万反应，免费检索。", images: ["/logo.png"] },
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
              <Link href="/" className="brand" aria-label="huagongshe.com 首页">
                <Image src="/logo.png" alt="" width={28} height={28} priority />
                <span className="brand-domain">
                  <span>huagongshe</span>
                  <span className="brand-divider" />
                  <span>.com</span>
                </span>
              </Link>
              <HeaderAccount />
            </div>
          </header>
          <main>{children}</main>
        </AccountProvider>
        <footer>
          <span>AIchem 开放数据计划：<a href="mailto:mail@huagongshe.com">mail@huagongshe.com</a></span>
        </footer>
      </body>
    </html>
  );
}
