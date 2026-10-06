/**
 * localePath · locale-aware 内部公开链接 helper
 *
 * withLocale("/search", "ja") → "/ja/search"; 保持当前 locale 的站内导航
 * 直接生成 locale URL, 不依赖 proxy 的 307 往返。
 * splitLocalePrefix("/ja/aichem") → { locale:"ja", rest:"/aichem" }; 唯一 locale 前缀 parser。
 * isPathAtOrBelow("/mcp-guide", "/mcp") → false; 路径边界语义 SSOT。
 *
 * 规则:
 *  - 外部 URL(http://…, https://…, mailto:…)原样返回, 不加前缀
 *  - NON_LOCALIZED_PREFIXES(全仓库唯一一张业务 prefix 表, proxy 与 link helper
 *    共用)与带扩展名的静态资源不加 locale; 边界语义由 isPathAtOrBelow 统一:
 *    "/mcp" 只排除自身与子树, 不排除 "/mcp-guide" 等同前缀字符串
 *  - 已带 locale 前缀的路径幂等返回, 不二次叠加(识别走同一 parser)
 *  - 不建第二份 locale 列表: 复用 SUPPORTED_LOCALES
 */

import { SUPPORTED_LOCALES, isSupportedLocale, type Locale } from "./i18n/locales";

/**
 * 不参与 locale 的路径前缀表 —— 全仓库唯一一张业务 prefix 表。
 * proxy 的 isExcluded() 与 withLocale() 都消费它; 任何地方不得再建第二份。
 */
export const NON_LOCALIZED_PREFIXES = [
  "/api",
  "/mcp",
  "/oauth",
  "/samelabs",
  "/.well-known",
  "/_next",
] as const;

/**
 * 路径边界语义: pathname 等于 prefix, 或位于 prefix 子树(prefix + "/")。
 * 是全站唯一的"前缀排除"判断 —— proxy 与 link helper 共用, 不允许第二套。
 * 注意 "/mcp" 不命中 "/mcp-guide"(非子树, 只是同前缀字符串)。
 */
export function isPathAtOrBelow(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/**
 * splitLocalePrefix · 唯一 locale 前缀 parser。
 *
 * "/ja/aichem" → { locale: "ja", rest: "/aichem" }
 * "/en"        → { locale: "en", rest: "/" }
 * "/en/"       → { locale: "en", rest: "/" }
 * "/chemical"  → null
 *
 * stripLocalePrefix / replaceLocalePrefix / withLocale / proxy 全部消费它,
 * 任何地方不得再出现第二份 locale 前缀 regex 或 segments 判断。
 */
export function splitLocalePrefix(pathname: string): { locale: Locale; rest: string } | null {
  const m = /^\/([^/]+)(\/.*)?$/.exec(pathname);
  if (!m) return null;
  const [, raw, tail = ""] = m;
  if (!isSupportedLocale(raw)) return null;
  return { locale: raw, rest: tail || "/" };
}

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
  // 前缀语义只看 pathname 部分, query 原样保留
  const queryAt = path.indexOf("?");
  const pathnameOnly = queryAt === -1 ? path : path.slice(0, queryAt);
  const query = queryAt === -1 ? "" : path.slice(queryAt);
  if (NON_LOCALIZED_PREFIXES.some((p) => isPathAtOrBelow(pathnameOnly, p))) return path;
  if (hasExtension(pathnameOnly)) return path;
  if (splitLocalePrefix(pathnameOnly)) return path; // 已带 locale, 幂等
  if (pathnameOnly === "/") return `/${locale}`;
  return `/${locale}${pathnameOnly}${query}`;
}

/**
 * applyLocale · 把内部公开路径强制切换到目标 locale。
 *
 * 与 withLocale 的幂等契约互补: withLocale 对已带 locale 前缀的路径原样返回
 * (大量既有调用依赖); applyLocale 则先把已有前缀剥掉再交给 withLocale 重建,
 * 用于"登录页切语言后, 登录成功的 next 回跳必须落在当前 locale"这类场景。
 * 复用 stripLocalePrefix + withLocale(排除表/静态资源/外部 URL 判定不建第二套):
 *  "/ja/aichem" + en → "/en/aichem"; "/aichem" + ko → "/ko/aichem";
 *  "/samelabs/users"、"/api/…"、静态文件、外部 URL → 原样; query 完整保留。
 */
export function applyLocale(path: string, locale: Locale): string {
  if (!path.startsWith("/")) return path; // 相对路径/锚点等不处理
  if (isExternal(path)) return path;
  // 前缀剥离只看 pathname, query 交给 withLocale 原样保留
  const queryAt = path.indexOf("?");
  const pathnameOnly = queryAt === -1 ? path : path.slice(0, queryAt);
  const query = queryAt === -1 ? "" : path.slice(queryAt);
  return withLocale(stripLocalePrefix(pathnameOnly) + query, locale);
}

/**
 * stripLocalePrefix · pathname locale 前缀剥离 SSOT(消费 splitLocalePrefix)。
 *
 * "/ja/aichem" → "/aichem"; "/en" → "/"; "/chemical/1" 原样。
 * 只处理 pathname, 不碰 query。无前缀/不支持的 locale 原样返回。
 * 全站组件不得再自行拆 segments 判断 locale 前缀。
 */
export function stripLocalePrefix(pathname: string): string {
  return splitLocalePrefix(pathname)?.rest ?? pathname;
}

/**
 * replaceLocalePrefix · 语言切换器的前缀替换 helper(自 LanguageSwitcher 迁入)。
 *
 * 把当前带前缀路径换成目标 locale 前缀; 无前缀(内部直访)时加前缀。
 * 只处理 pathname, 不含 query —— query 由调用方用当前路由状态拼接。
 */
export function replaceLocalePrefix(pathname: string, next: Locale): string {
  const parsed = splitLocalePrefix(pathname);
  if (parsed) return `/${next}${parsed.rest === "/" ? "" : parsed.rest}`;
  return `/${next}${pathname === "/" ? "" : pathname}`;
}

export type { Locale };
export { SUPPORTED_LOCALES };
