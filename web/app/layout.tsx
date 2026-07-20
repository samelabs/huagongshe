import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { HeaderAccount } from "@/components/HeaderAccount";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://huagongshe.com"),
  title: { default: "化工社｜开放化学数据", template: "%s｜化工社" },
  description: "查询、补充和维护化合物与化学反应数据。",
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "化工社｜开放化学数据",
    description: "查询、补充和维护化合物与化学反应数据。",
    url: "/",
    siteName: "化工社",
    locale: "zh_CN",
    type: "website",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <header className="site-header">
          <div className="header-inner">
            <Link href="/" className="brand" aria-label="huagongshe.com 首页">
              <Image src="/icon.svg" alt="" width={28} height={28} priority />
              <span>huagongshe.com</span>
            </Link>
            <HeaderAccount />
          </div>
        </header>
        <main>{children}</main>
        <footer>
          <span>huagongshe.com</span>
          <span>开放数据，共同维护</span>
        </footer>
      </body>
    </html>
  );
}
