import type { MetadataRoute } from "next";

import { FALLBACK_LOCALE, SITE_ORIGIN, localizedAbsoluteUrl } from "@/lib/alternates";

/**
 * 静态 Sitemap：只收录公开、可索引、有独立 canonical 的入口页，每页一份。
 * 入口页是隐性多语言（无 hreflang，见 lib/alternates.ts 多语言边界）：只列
 * 回退语言（en，与无语言偏好访问的协商结果一致）一份，不宣告其他语言的重复 URL。
 *
 * 不收录：工作台、登录、后台、账户、参数化检索页、动态实体页（化合物、反应、
 * 笔记、用户主页），以及条款、隐私、支持页（由页脚进入）。
 * 无可靠修改时间，不输出 lastModified。
 */
/* /skills 是登录能力(私有面), 不进 sitemap */
const PUBLIC_STATIC_PATHS = [
  "/",
  "/search",
  "/guide",
  "/mcp-guide",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_STATIC_PATHS.map((path) => ({ url: localizedAbsoluteUrl(path, FALLBACK_LOCALE) }));
}

/** robots.ts 复用的 Sitemap 绝对 URL。 */
export const SITEMAP_URL = `${SITE_ORIGIN}/sitemap.xml`;
