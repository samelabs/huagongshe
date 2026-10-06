/**
 * proxy.ts · 公开 Web 的 locale URL 路由骨架(Next.js 16 proxy, 无 middleware.ts)
 *
 * 只做两件事, 不切换页面字典、不改文案:
 *  1. 已带 locale 前缀的公开路径(/ja/chemical/123)→ rewrite 到现有路由
 *     (/chemical/123), 浏览器地址保持 /ja/chemical/123; 内部请求附带
 *     x-site-locale header 传递明确 locale;/ja → /。
 *  2. 未带 locale 的公开路径 → 按 cookie(site_locale) > Accept-Language >
 *     en 的顺序协商, 307 redirect 到带 locale 前缀的 URL(pathname 与
 *     query string 完整保留); 进入明确 locale URL 时同步 cookie。
 *
 * 排除路径完全不参与(行为不变): /api/* /mcp /oauth/* /.well-known/* /_next/*
 * /samelabs/* 以及 favicon/robots/sitemap/manifest/service worker/
 * public 静态文件等带扩展名资源。
 *
 * locale 列表单一权威: 直接复用 lib/i18n/locales.ts, 不建第二份。
 */

import { NextResponse, type NextRequest } from "next/server";

import { SUPPORTED_LOCALES, FALLBACK_LOCALE, isSupportedLocale, type Locale } from "./lib/i18n/locales";
import { NON_LOCALIZED_PREFIXES, isPathAtOrBelow, splitLocalePrefix } from "./lib/localePath";

/** 站点 locale cookie(值只允许 SUPPORTED_LOCALES 中的 locale) */
const LOCALE_COOKIE = "site_locale";

/** 传递给内部请求的 locale header(全站只此一个) */
const LOCALE_HEADER = "x-site-locale";

/** rewrite 时附带原始(带 locale 前缀的)请求路径, 供 server 端构建 locale-aware 回跳(next)参数 */
const LOCALE_PATH_HEADER = "x-site-locale-path";

/** cookie 属性: 1 年, Lax */
const LOCALE_COOKIE_OPTIONS = { path: "/", maxAge: 31536000, sameSite: "lax" as const };

/** 按名称排除的根级文件(favicon/robots/sitemap/manifest/service worker 等) */
const EXCLUDED_FILES = new Set([
  "/favicon.ico",
  "/robots.txt",
  "/sitemap.xml",
  "/manifest.json",
  "/manifest.webmanifest",
  "/sw.js",
  "/service-worker.js",
]);

function isExcluded(pathname: string): boolean {
  // 前缀排除走统一路径边界语义(NON_LOCALIZED_PREFIXES 是全仓库唯一业务 prefix 表):
  // "/mcp" 只排除 /mcp 与 /mcp/*, 不排除 /mcp-guide
  if (NON_LOCALIZED_PREFIXES.some((p) => isPathAtOrBelow(pathname, p))) return true;
  if (EXCLUDED_FILES.has(pathname)) return true;
  // 带文件扩展名的资源(public 静态文件 / icon 等), 例如 .png .css .js .xml .txt .webmanifest
  const last = pathname.split("/").pop() ?? "";
  return /\.[A-Za-z0-9]+$/.test(last);
}

/** Accept-Language 协商: 返回第一个受支持的语言, 无则 null */
function negotiateAcceptLanguage(header: string | null): Locale | null {
  if (!header) return null;
  const candidates = header
    .split(",")
    .map((part) => {
      const [tag, ...params] = part.trim().split(";").map((s) => s.trim());
      let q = 1;
      for (const p of params) {
        const [k, v] = p.split("=");
        if (k === "q") q = Number.parseFloat(v) || 0;
      }
      return { tag, q };
    })
    .filter((c) => c.tag && c.q > 0)
    .sort((a, b) => b.q - a.q);
  for (const { tag } of candidates) {
    const lower = tag.toLowerCase();
    // 精确匹配: zh-CN / en / ja / ko / de
    const exact = SUPPORTED_LOCALES.find((l) => l.toLowerCase() === lower);
    if (exact) return exact;
    // 主语言匹配: ja-JP → ja, de-DE → de, en-US → en
    const primary = lower.split("-")[0];
    if (primary === "zh") return "zh-CN"; // zh/zh-TW/zh-HK 等统一 zh-CN(现有唯一中文变体)
    const byPrimary = SUPPORTED_LOCALES.find((l) => l.toLowerCase().split("-")[0] === primary);
    if (byPrimary) return byPrimary;
  }
  return null;
}

/** 未带 locale 的公开路径: cookie > Accept-Language > en */
function detectLocale(cookieHeader: string | null, acceptLanguage: string | null): Locale {
  if (cookieHeader) {
    const cookie = cookieHeader
      .split(";")
      .map((c) => c.trim())
      .find((c) => c.startsWith(`${LOCALE_COOKIE}=`));
    if (cookie) {
      const raw = cookie.slice(LOCALE_COOKIE.length + 1);
      // malformed cookie(如非法 % 序列)会让 decodeURIComponent 抛 URIError → 500;
      // 只保护 decode: 异常值忽略, 继续走 Accept-Language → FALLBACK_LOCALE。
      // 不删 cookie、不加额外响应逻辑。
      try {
        const value = decodeURIComponent(raw);
        if (isSupportedLocale(value)) return value;
      } catch {
        // malformed cookie: ignore and continue locale negotiation
      }
    }
  }
  return negotiateAcceptLanguage(acceptLanguage) ?? FALLBACK_LOCALE;
}

export default function proxy(request: NextRequest): NextResponse | undefined {
  const pathname = request.nextUrl.pathname;

  if (isExcluded(pathname)) return undefined;

  const prefixed = splitLocalePrefix(pathname);
  if (prefixed) {
    // locale 前缀 + excluded path(如 /ja/mcp、/ja/api/health)是无效 alias:
    // excluded 前缀完全不参与 locale, 不 rewrite 到 stripped path(避免第二套 alias),
    // 交给后续路由按原路径 404。
    if (isExcluded(prefixed.rest)) return undefined;

    // 已带 locale: Next 原生 rewrite 到现有路由, 地址栏不变, 附带 locale header, 同步 cookie
    const rewriteUrl = request.nextUrl.clone();
    rewriteUrl.pathname = prefixed.rest;
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set(LOCALE_HEADER, prefixed.locale);
    requestHeaders.set(LOCALE_PATH_HEADER, pathname + request.nextUrl.search);
    const response = NextResponse.rewrite(rewriteUrl, { request: { headers: requestHeaders } });
    response.cookies.set(LOCALE_COOKIE, prefixed.locale, LOCALE_COOKIE_OPTIONS);
    return response;
  }

  // 未带 locale: 协商后 redirect(保留 pathname 与 query string), 同步 cookie
  const locale = detectLocale(request.headers.get("cookie"), request.headers.get("accept-language"));
  const response = NextResponse.redirect(
    new URL(`/${locale}${pathname === "/" ? "/" : pathname}${request.nextUrl.search}`, request.url),
    307,
  );
  response.cookies.set(LOCALE_COOKIE, locale, LOCALE_COOKIE_OPTIONS);
  return response;
}

export const config = {
  matcher: [
    /*
     * matcher 只做 Next/framework 静态资源层面的优化(_next 与根级静态文件);
     * 公开业务路径分类(api/mcp/oauth/.well-known/samelabs 等)不在这里复制第二套
     * prefix 规则 —— 由 runtime isExcluded() → isPathAtOrBelow() SSOT 决定。
     * Next 16 proxy matcher 不支持负向前瞻, 用分段排除。
     */
    "/((?!_next|favicon\\.ico|robots\\.txt|sitemap\\.xml|manifest\\.json|manifest\\.webmanifest|sw\\.js|service-worker\\.js).*)",
  ],
};
