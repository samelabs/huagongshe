import type { MetadataRoute } from "next";

import { SITE_ORIGIN, localizedAbsoluteUrl } from "@/lib/alternates";
import { SUPPORTED_LOCALES, FALLBACK_LOCALE } from "@/lib/i18n/locales";

/**
 * S1 (G1.5-A/A2-1): 基础静态 Sitemap —— 只收录确实存在、公开可索引、
 * 有明确 canonical 的静态页面。
 *
 * 收录一致性(A2-1):
 *  - Home/Search/Guide/MCP Guide/Skills: 五语言版本(各有独立 canonical)。
 *  - Terms/Privacy/Support: 仅英文正式版本(唯一 canonical = /en/*,
 *    非英文路径 noindex, 不进入 Sitemap)。
 *
 * 边界(与管理端指令一致):
 *  - 不收录工作台(/aichem)、登录、后台、账户、参数化检索页(/search?q=)。
 *  - 不收录动态 HCID/HRID/Note(动态实体 Sitemap 属后续批次, 禁止在
 *    构建期枚举数字 ID、全表扫描或无界 API 分页)。
 *  - 不伪造 lastModified: 本批全部为无可靠修改时间的静态页, 不输出该字段。
 *  - origin 与 URL 构建复用 lib/alternates SSOT(SITE_ORIGIN/withLocale),
 *    不出现第二份域名/前缀逻辑。
 */

/** 白名单: 无前缀公开静态路径(不存在动态段, 不含任何参数化页面)。 */
const PUBLIC_STATIC_PATHS = [
  "/",
  "/search",
  "/guide",
  "/mcp-guide",
  "/skills",
] as const;

/** 法律/支持页: 只有英文正式版可索引, 其唯一 canonical 在 /en/*。 */
const ENGLISH_ONLY_PATHS = ["/terms", "/privacy", "/support"] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    ...SUPPORTED_LOCALES.flatMap((locale) =>
      PUBLIC_STATIC_PATHS.map((path) => ({
        url: localizedAbsoluteUrl(path, locale),
        // 无真实修改时间可依 —— 宁缺毋假, 不输出 lastModified/changeFrequency/priority
      })),
    ),
    ...ENGLISH_ONLY_PATHS.map((path) => ({
      url: localizedAbsoluteUrl(path, "en"),
    })),
  ];
}

/** robots.ts 复用: Sitemap 绝对 URL(与 sitemap() 同一 SSOT, 单一来源)。 */
export const SITEMAP_URL = `${SITE_ORIGIN}/sitemap.xml`;

// 防御性再导出说明: FALLBACK_LOCALE 供后续动态实体批次决定 x-default 语义,
// 本静态批次不使用 —— 显式 import 而非未用引入会破坏 lint, 故仅注释声明。
void FALLBACK_LOCALE;
