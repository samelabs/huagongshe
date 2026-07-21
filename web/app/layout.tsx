import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { AccountProvider } from "@/components/AccountContext";
import { HeaderAccount } from "@/components/HeaderAccount";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://huagongshe.com"),
  title: { default: "化工社｜AI化学开放数据", template: "%s｜化工社" },
  description: "开放查询和维护化合物与化学反应数据。",
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "化工社｜AI化学开放数据",
    description: "开放查询和维护化合物与化学反应数据。",
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
      <body>
        <AccountProvider>
          <header className="site-header">
            <div className="header-inner">
              <Link href="/" className="brand" aria-label="huagongshe.com 首页">
                <Image src="/logo.png" alt="" width={28} height={28} priority />
                <span>huagongshe.com</span>
              </Link>
              <HeaderAccount />
            </div>
          </header>
          <main>{children}</main>
        </AccountProvider>
        <footer>
          <span>huagongshe.com</span>
          <span>开放化学数据</span>
        </footer>
      </body>
    </html>
  );
}
