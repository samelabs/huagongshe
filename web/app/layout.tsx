import type { Metadata } from "next";
import Link from "next/link";
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
            <Link href="/" className="brand" aria-label="化工社首页">
              <span>化工社</span>
            </Link>
            <nav aria-label="主导航">
              <Link href="/submit">提交</Link>
              <Link href="/login" className="login-link">登录</Link>
            </nav>
          </div>
        </header>
        <main>{children}</main>
        <footer>开放化学数据 · 非商业化</footer>
      </body>
    </html>
  );
}
