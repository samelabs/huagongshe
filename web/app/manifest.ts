import type { MetadataRoute } from "next";
import { cookies } from "next/headers";
import { getDictionary } from "@/lib/i18n";
import { isSupportedLocale, FALLBACK_LOCALE } from "@/lib/i18n/locales";
import { withLocale } from "@/lib/localePath";
import { pwaAppName } from "@/lib/pwa";

/**
 * PWA manifest 唯一 owner(Next metadata file convention, 替代原静态
 * public/manifest.webmanifest)。
 *
 * locale 来源: site_locale cookie(proxy 写入)。
 *  - cookie 是 supported locale → 用它
 *  - 缺失/非法 → FALLBACK_LOCALE(en) —— 与公开站无 locale 的协商 fallback 一致,
 *    不是 SITE_LOCALE(zh-CN)
 *
 * name/short_name 复用 pwaAppName(); description 复用既有字典
 * brand.seoDescShort(不新增翻译); start_url 复用 withLocale("/", locale)
 * 避免 trailing-slash redirect。
 */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const cookieLocale = (await cookies()).get("site_locale")?.value ?? "";
  const locale = isSupportedLocale(cookieLocale) ? cookieLocale : FALLBACK_LOCALE;
  const name = pwaAppName(locale);
  const t = await getDictionary(locale);

  return {
    name,
    short_name: name,
    description: t.brand.seoDescShort,
    start_url: withLocale("/", locale),
    scope: "/",
    display: "standalone",
    background_color: "#f5f9ff",
    theme_color: "#1e90ff",
    lang: locale,
    orientation: "any",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
