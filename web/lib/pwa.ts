/**
 * pwa · PWA 外显产品名称唯一 owner
 *
 * manifest name/short_name 与 iOS appleWebApp title 共用这一条规则,
 * 不允许出现第二份命名逻辑。
 * 规则: zh-CN → 化工社, 其余(en/ja/ko/de) → HGS。
 */

import type { Locale } from "./i18n/locales";

export function pwaAppName(locale: Locale): string {
  return locale === "zh-CN" ? "化工社" : "HGS";
}
