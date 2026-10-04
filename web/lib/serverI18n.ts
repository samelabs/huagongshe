/**
 * server i18n · 从当前请求读取运行时 locale (server-only)
 *
 * 链路: proxy.ts 协商后通过 x-site-locale header 传入内部请求 →
 * getRequestLocale() 读取 → getDictionary(locale) 取字典。
 *
 * 规则:
 *  - header 值 ∈ SUPPORTED_LOCALES → 使用该 locale
 *  - header 缺失或非法 → SITE_LOCALE(当前 zh-CN), 保持未经过 locale proxy
 *    的内部页面(/samelabs、API SSR 等)现状
 *  - 不从 cookie / Accept-Language 再判断; 协商只属于 proxy.ts
 *
 * 字典注册逻辑复用 lib/i18n/index.ts 的 getDictionary, 不建第二份。
 */

// 注: 未引入 server-only 包(依赖最小化); 本文件只被 server 组件 import。

import { headers } from "next/headers";

import { getDictionary } from "./i18n";
import { isSupportedLocale, type Locale } from "./i18n/locales";
import { SITE_LOCALE } from "./locale";

/** proxy → 内部请求传递 locale 的唯一 header(与 web/proxy.ts 的 LOCALE_HEADER 一致) */
const LOCALE_HEADER = "x-site-locale";

/** 当前请求的 locale: header 合法则用之, 否则站点默认 SITE_LOCALE */
export async function getRequestLocale(): Promise<Locale> {
  const header = (await headers()).get(LOCALE_HEADER);
  if (header && isSupportedLocale(header)) return header;
  return SITE_LOCALE;
}

/** 当前请求 locale 对应的字典(复用现有 getDictionary, 不建第二份注册) */
export async function getRequestDictionary() {
  return getDictionary(await getRequestLocale());
}
