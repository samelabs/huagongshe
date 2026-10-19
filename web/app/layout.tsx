import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import { AccountProvider } from "@/components/shared/AccountContext";
import { I18nProvider } from "@/components/shared/I18nContext";
import { ToastProvider } from "@/components/ui/Toast";
import { ConfirmProvider } from "@/components/ui/ConfirmDialog";
import { HydrationMarker } from "@/components/shell/HydrationMarker";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { ShellWorkbenchChromeProvider } from "@/components/shell/ShellWorkbenchChrome";
import { getShellWorkbenchChrome } from "@/lib/shellData";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { SITE_ORIGIN } from "@/lib/alternates";
import { pwaAppName } from "@/lib/pwa";
import { apiGet } from "@/lib/api.server";
import type { User } from "@/lib/api";
import "./tokens.css";
import "./globals.css";
import "./account-menu.css";
// 组件库样式：tokens.css 之后引入（组件类名 .hg- 覆盖全局默认）
import "../components/ui/ui.css";
// 全局框架（SiteHeader 顶栏 + MobileTabBar 底栏），公开页与工作台共用
import "../components/shell/shell.css";
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
    // 不再全局输出 robots=index,follow —— 缺席即默认可索引；
    // 404 页由 Next 自动注入唯一一条 noindex（此前会与本条叠加成两条）。
  };
}

type SiteConfig = {
  analytics?: { scripts?: { provider?: string; enabled?: boolean; id?: string } };
  ads?: { adsense?: { enabled?: boolean; client?: string } };
};

// 缓存：config 低频变更（admin 改 system_config），最迟 300s 生效
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
  const edgeCache = h.get("x-site-edge-cache") ?? "private";
  const cookieStore = await cookies();
  const initialUser = (edgeCache !== "public" && cookieStore.has("hgs_session"))
    ? await getSSRUser(h.get("cookie"))
    : null;
  // 运行时 locale 链路: proxy(x-site-locale) → getRequestLocale → I18nProvider。
  // 全站公开页面已按 locale 输出, lang 与 runtime locale 保持一致。
  // hydration: root layout 为 server render, lang 由请求 header(SSOT)决定,
  // client 无二次推断, 不产生 hydration mismatch。
  const locale = await getRequestLocale();
  // 外壳的工作台形态数据：只在请求命中工作台路由且有会话时取（同渲染
  // 与工作台 layout 合并请求）；作为顶栏工作台上下文的初始值。
  const chrome = await getShellWorkbenchChrome();

  return (
    // data-build：dev-only 的 commit 指纹（next.config env 注入），线上只读
    // 截图断言用；生产构建下 undefined 不输出该属性。
    <html lang={locale} data-build={process.env.HGS_BUILD_SHA || undefined}>
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
        <AccountProvider initialUser={initialUser} resolved={edgeCache !== "public"}>
          <I18nProvider locale={locale}>
            <ToastProvider>
              <ConfirmProvider>
                {/* 全站唯一外壳（顶栏 + 手机底栏）：在根 layout 挂一次，
                    公开页与工作台之间切换路由不卸载重建。
                    工作台形态（手机动作 ≡/+ 与未读数）经上下文供给：初始值
                    来自本层服务端取数；站内切进工作台后由工作台 layout 的
                    Sync 组件写入，顶栏不重挂即切换形态。
                    顶栏与页面同在一个满屏框架内：框架占满视口，页面填满顶栏以下的剩余高度。 */}
                <div className="sh-frame">
                  <ShellWorkbenchChromeProvider initial={chrome}>
                    <SiteHeader />
                    {children}
                  </ShellWorkbenchChromeProvider>
                </div>
                {/* 水合哨兵：挂载后 <html data-hydrated=1>，截图工具等待它 */}
                <HydrationMarker />
              </ConfirmProvider>
            </ToastProvider>
          </I18nProvider>
        </AccountProvider>
        {/* sw.js 对 /_next/static 缓存优先，前提是文件名带内容哈希 —— 只有生产构建满足；
            开发服务器的文件名不随内容变，注册会把旧样式永久钉在缓存里，故开发时注销。 */}
        <script dangerouslySetInnerHTML={{ __html: process.env.NODE_ENV === "production"
          ? `if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})})}`
          : `if('serviceWorker' in navigator){navigator.serviceWorker.getRegistrations().then(function(rs){rs.forEach(function(r){r.unregister()})});if(window.caches){caches.keys().then(function(ks){ks.forEach(function(k){caches.delete(k)})})}}` }} />
      </body>
    </html>
  );
}
