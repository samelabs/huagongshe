/**
 * localePath · locale-aware 内部公开链接 helper
 *
 * withLocale("/search", "ja") → "/ja/search"; 保持当前 locale 的站内导航
 * 直接生成 locale URL, 不依赖 proxy 的 307 往返。
 *
 * 规则:
 *  - 外部 URL(http://…, https://…, mailto:…)原样返回, 不加前缀
 *  - /api、/mcp、/samelabs、/.well-known、/_next 与带扩展名的静态资源不加 locale
 *    (与 proxy.ts 的排除口径一致, 但本 helper 只需排除"不该带 locale 的公开前缀")
 *  - 已带 locale 前缀的路径幂等返回, 不二次叠加
 *  - 不建第二份 locale 列表: 复用 SUPPORTED_LOCALES
 */

import { SUPPORTED_LOCALES, isSupportedLocale, type Locale } from "./i18n/locales";

/** 不加 locale 前缀的路径(与 proxy 排除口径保持一致) */
const NO_LOCALE_PREFIXES = ["/api", "/mcp", "/samelabs", "/.well-known", "/_next"];

function isExternal(path: string): boolean {
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(path) || path.startsWith("//");
}

function hasExtension(path: string): boolean {
  const last = path.split("/").pop() ?? "";
  return /\.[A-Za-z0-9]+$/.test(last);
}

export function withLocale(path: string, locale: Locale): string {
  if (!path.startsWith("/")) return path; // 相对路径/锚点等不处理
  if (isExternal(path)) return path;
  if (NO_LOCALE_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`))) return path;
  if (hasExtension(path)) return path;
  const segments = path.split("/");
  if (segments.length > 1 && isSupportedLocale(segments[1])) return path; // 已带 locale, 幂等
  if (path === "/") return `/${locale}`;
  return `/${locale}${path}`;
}

export type { Locale };
export { SUPPORTED_LOCALES };
