import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { AccountProvider } from "@/components/shared/AccountContext";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import "./globals.css";
import t from "@/lib/i18n";
export const viewport: Viewport = {
  themeColor: "#1e90ff",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};
export const metadata: Metadata = {
  metadataBase: new URL("https://huagongshe.com"),
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "化工社", statusBarStyle: "default" },
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
};

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
          {children}
        </AccountProvider>
        <script dangerouslySetInnerHTML={{ __html: `if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})})}` }} />
      </body>
    </html>
  );
}
