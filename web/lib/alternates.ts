/**
 * alternates · canonical / hreflang 构建小 helper
 *
 * 单一职责: 给定无前缀公开路径 → 按 Next Metadata API 的 alternates 形态
 * 返回当前语言 canonical + 五语言 hreflang + x-default。
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
