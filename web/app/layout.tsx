import type { Metadata } from "next";
import Link from "next/link";
import { headers } from "next/headers";
import { AccountProvider } from "@/components/AccountContext";
import { HeaderAccount } from "@/components/HeaderAccount";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import "./globals.css";
import t from "@/lib/i18n";
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

export const dynamic = "force-dynamic";

async function getSiteConfig(): Promise<SiteConfig> {
  try { return await apiGet<SiteConfig>("/config"); }
  catch { return {}; }
}

async function getSSRUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const config = await getSiteConfig();
  const analytics = config.analytics?.scripts;
  const adsense = config.ads?.adsense;
  const footerSlogan = config.branding?.slogan?.footer || t.brand.slogan;
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const initialUser = await getSSRUser(cookieHeader);

  return (
    <html lang="zh-CN">
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
        <AccountProvider initialUser={initialUser}>
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
          <span>AIchem开放计划：<a href="mailto:mail@huagongshe.com" style={{ color: "var(--blue)" }}>mail@huagongshe.com</a></span>
        </footer>
      </body>
    </html>
  );
}
