import type { MetadataRoute } from "next";

import { SITE_ORIGIN, localizedAbsoluteUrl } from "@/lib/alternates";
import { SUPPORTED_LOCALES } from "@/lib/i18n/locales";

/**
 * 静态 Sitemap：只收录公开、可索引、有独立 canonical 的入口页，五语言各一份。
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
  return SUPPORTED_LOCALES.flatMap((locale) =>
    PUBLIC_STATIC_PATHS.map((path) => ({ url: localizedAbsoluteUrl(path, locale) })),
  );
}

/** robots.ts 复用的 Sitemap 绝对 URL。 */
export const SITEMAP_URL = `${SITE_ORIGIN}/sitemap.xml`;
