import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { AccountProvider } from "@/components/shared/AccountContext";
import { I18nProvider } from "@/components/shared/I18nContext";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { SITE_ORIGIN } from "@/lib/alternates";
import { pwaAppName } from "@/lib/pwa";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import "./tokens.css";
import "./globals.css";
import "./account-menu.css";
export const viewport: Viewport = {
  // metadata 约定只接受字符串字面量，无法引用 CSS 变量；此值与 tokens.css 的 --brand(blue-500) 一致
  themeColor: "#1e90ff",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};
export async function generateMetadata(): Promise<Metadata> {
  // root 只保留真正全站级 metadata —— alternates/openGraph/twitter 属于具体页面
  // (首页在 (site)/page.tsx 自持), 放这里会污染未覆盖 metadata 的子页面。
  // manifest 由 app/manifest.ts(metadata file convention)接管, 此处不再声明。
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    metadataBase: new URL(SITE_ORIGIN),
    appleWebApp: { capable: true, title: pwaAppName(locale), statusBarStyle: "default" },
    title: { default: t.brand.seoTitle, template: `%s｜${t.brand.name}` },
    description: t.brand.seoDesc,
    keywords: [...t.brand.keywords, "AI Chemistry Workspace", "Chemical Knowledge Base", "Reaction Library"],
    robots: { index: true, follow: true },
  };
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
  // The admin-configured ID is interpolated into inline JS: validate its grammar first.
  const analyticsId = analytics?.provider === "51la" && typeof analytics.id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(analytics.id)
    ? analytics.id : null;
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
        {analytics?.enabled && analyticsId && (
          <>
            <script charSet="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js" />
            <script dangerouslySetInnerHTML={{ __html: `LA.init({id:${JSON.stringify(analyticsId)},ck:${JSON.stringify(analyticsId)}})` }} />
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
