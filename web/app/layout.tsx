import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { AccountProvider } from "@/components/shared/AccountContext";
import { I18nProvider } from "@/components/shared/I18nContext";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeAlternates } from "@/lib/alternates";
import { withLocale } from "@/lib/localePath";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import "./globals.css";
import "./account-menu.css";
export const viewport: Viewport = {
  themeColor: "#1e90ff",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    metadataBase: new URL("https://huagongshe.com"),
    manifest: "/manifest.webmanifest",
    appleWebApp: { capable: true, title: t.brand.name, statusBarStyle: "default" },
    title: { default: t.brand.seoTitle, template: `%s｜${t.brand.name}` },
    description: t.brand.seoDesc,
    keywords: [...t.brand.keywords, "AI Chemistry Workspace", "Chemical Knowledge Base", "Reaction Library"],
    // 首页 canonical/hreflang: 当前语言正式 URL + 五语言 alternate + x-default(en)
    alternates: localeAlternates("/", locale),
    robots: { index: true, follow: true },
    openGraph: {
      title: t.brand.seoTitle,
      description: t.brand.seoDesc,
      url: withLocale("/", locale),
      siteName: t.brand.name,
      locale: ogLocaleTag(locale),
      type: "website",
      images: [{ url: "/logo.png", width: 512, height: 512, alt: t.brand.ogAlt }],
    },
    twitter: { card: "summary", title: t.brand.seoTitle, description: t.brand.seoDescShort, images: ["/logo.png"] },
  };
}

/** Open Graph locale 语义: language_TERRITORY 格式(zh-CN → zh_CN 等); 仅影响 og:meta, 不动 URL/hreflang/lang */
function ogLocaleTag(locale: string): string {
  switch (locale) {
    case "zh-CN": return "zh_CN";
    case "en": return "en_US";
    case "ja": return "ja_JP";
    case "ko": return "ko_KR";
    case "de": return "de_DE";
    default: return "en_US";
  }
}

type SiteConfig = {
  analytics?: { scripts?: { provider?: string; enabled?: boolean; id?: string } };
  ads?: { adsense?: { enabled?: boolean; client?: string } };
};

// A档缓存：config 低频变更（admin 改 system_config），最迟 300s 生效
async function getSiteConfig(): Promise<SiteConfig> {
  try { return await apiGet<SiteConfig>("/config", undefined, { revalidate: 300 }); }
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
  // 运行时 locale 链路: proxy(x-site-locale) → getRequestLocale → I18nProvider。
  // 全站公开页面已按 locale 输出, lang 与 runtime locale 保持一致。
  // hydration: root layout 为 server render, lang 由请求 header(SSOT)决定,
  // client 无二次推断, 不产生 hydration mismatch。
  const locale = await getRequestLocale();

  return (
    <html lang={locale}>
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
          <I18nProvider locale={locale}>
            {children}
          </I18nProvider>
        </AccountProvider>
        <script dangerouslySetInnerHTML={{ __html: `if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})})}` }} />
      </body>
    </html>
  );
}
