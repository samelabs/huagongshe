import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { AccountProvider } from "@/components/AccountContext";
import { HeaderAccount } from "@/components/HeaderAccount";
import "./globals.css";
import Script from "next/script";

export const metadata: Metadata = {
  metadataBase: new URL("https://huagongshe.com"),
  title: { default: "化工社｜开放化学数据与个人反应记录", template: "%s｜化工社" },
  description: "查询开放化学数据，保存和管理自己的反应记录。",
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "化工社｜开放化学数据与个人反应记录",
    description: "查询开放化学数据，保存和管理自己的反应记录。",
    url: "/",
    siteName: "化工社",
    locale: "zh_CN",
    type: "website",
    images: [{ url: "/logo.png", width: 512, height: 512, alt: "化工社" }],
  },
  twitter: { card: "summary", images: ["/logo.png"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <head>
        <script charSet="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js" />
        <script dangerouslySetInnerHTML={{ __html: 'LA.init({id:"1vMIAXQLAZjjdeBt",ck:"1vMIAXQLAZjjdeBt"})' }} />
      </head>
      <body>
        <Script
          async
          src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2925838645350883"
          crossOrigin="anonymous"
          strategy="afterInteractive"
        />
        <AccountProvider>
          <header className="site-header">
            <div className="header-inner">
              <Link href="/" className="brand" aria-label="huagongshe.com 首页">
                <Image src="/logo.png" alt="" width={28} height={28} priority />
                <span className="brand-domain"><span>huagongshe</span><span>.com</span></span>
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
