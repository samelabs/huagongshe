import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { HeaderAccount } from "@/components/HeaderAccount";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://huagongshe.com"),
  title: { default: "化工社｜化合物与反应数据", template: "%s｜化工社" },
  description: "查询化合物、结构与反应数据。",
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "化工社｜化合物与反应数据",
    description: "查询化合物、结构与反应数据。",
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
        <footer>开放化学数据 · 非商业化</footer>
      </body>
    </html>
  );
}
