/**
 * alternates · canonical / hreflang / OG locale / 绝对 URL 构建小 helper
 *
 * 单一职责: 给定无前缀公开路径 → 按 Next Metadata API 的 alternates 形态
 * 返回当前语言 canonical + 五语言 hreflang + x-default; 以及全站唯一的
 * ogLocaleTag 映射与 SITE_ORIGIN 绝对 URL。
 *
 * 规则(与 proxy.ts / localePath.ts 同一 locale 体系, 不建第二份):
 *  - canonical 用正式 locale 前缀 URL(相对路径, metadataBase 负责拼域名)
 *  - hreflang 覆盖 SUPPORTED_LOCALES 全部五种语言
 *  - x-default → FALLBACK_LOCALE(en) 版本
 *  - path 必须是无前缀内部路径(如 /chemical/2244); 由调用方保证
 */

import type { Metadata } from "next";
import { SUPPORTED_LOCALES, FALLBACK_LOCALE, type Locale } from "./i18n/locales";
import { withLocale } from "./localePath";

/** 站点正式 origin —— metadataBase 与 JSON-LD 绝对 URL 共用, 不允许出现第三份字面量 */
export const SITE_ORIGIN = "https://huagongshe.com";

/** Open Graph locale 标签: language_TERRITORY 格式; Record 显式映射, 不用 default 掩盖非法 Locale */
const OG_LOCALE_TAGS: Record<Locale, string> = {
  "zh-CN": "zh_CN",
  en: "en_US",
  ja: "ja_JP",
  ko: "ko_KR",
  de: "de_DE",
};

/** og:locale 唯一 owner(原 app/layout.tsx 私有版与 skills 三元表达式已收敛到此) */
export function ogLocaleTag(locale: Locale): string {
  return OG_LOCALE_TAGS[locale];
}

/** 当前 locale 正式绝对 URL(JSON-LD 等需要 absolute URL 的场合): SITE_ORIGIN + withLocale */
export function localizedAbsoluteUrl(path: string, locale: Locale): string {
  return SITE_ORIGIN + withLocale(path, locale);
}

export function localeAlternates(path: string, locale: Locale): Metadata["alternates"] {
  return {
    canonical: withLocale(path, locale),
    languages: {
      ...Object.fromEntries(
        SUPPORTED_LOCALES.map((l) => [l, withLocale(path, l)] as const)
      ),
      // x-default → English(未知语言 fallback, 与 FALLBACK_LOCALE 一致)
      "x-default": withLocale(path, FALLBACK_LOCALE),
    },
  };
}

// Object.fromEntries 的 key 类型收敛(hreflang tag 即 locale 名)
export type { Locale };
export { SUPPORTED_LOCALES, FALLBACK_LOCALE };
