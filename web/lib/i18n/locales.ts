/**
 * i18n locale 定义 · 与 web/lib/locale.ts 协调的单一权威来源
 *
 * - SUPPORTED_LOCALES: 站点支持的全部 locale(zh-CN/en/ja/ko/de)
 * - FALLBACK_LOCALE: 未知/未支持 locale 的 fallback(英文);
 *   五语言均已提供完整字典并注册。
 * - Locale / NonFallbackLocale: 从 SUPPORTED_LOCALES 推导的字符串字面量
 *   联合类型, 不手写第二份列表。
 *
 * web/lib/locale.ts 的 SITE_LOCALE(= zh-CN, formatter/名称解析用常量)与本
 * 文件分工: 本文件负责字典体系的 locale 列表, locale.ts 负责 formatter;
 * 两者互不 import、无循环依赖, locale 列表只在下面这一处维护。
 */

/** 站点支持的 locale(有序, 首位为默认语言 zh-CN) */
export const SUPPORTED_LOCALES = ["zh-CN", "en", "ja", "ko", "de"] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

/** 未知/未支持 locale 一律回落的 fallback locale(英文) */
export const FALLBACK_LOCALE: Locale = "en";

export function isSupportedLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}
