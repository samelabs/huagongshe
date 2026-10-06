/**
 * i18n 字典机制入口
 *
 * 结构:
 *   lib/i18n/locales.ts      locale 定义(唯一权威列表) + fallback 规则
 *   lib/i18n/locales/*.ts    五语言完整字典: zh-CN / en / ja / ko / de
 *                            (均已注册, 同一 Dictionary 结构, tsc 校验)
 *   lib/i18n/index.ts        本文件: 字典注册表 + getDictionary + 兼容出口
 *
 * 字典类型: Dictionary = typeof zhCN —— 直接从中文字典推导(as const 对象
 * 的字面量类型), 不手写第二份 interface, en/ja/ko/de 字典满足
 * 同一 Dictionary 结构。
 *
 * fallback: 未知 locale → FALLBACK_LOCALE(en)。五语言字典均已注册,
 * getDictionary 对未注册 locale(白名单外的值)抛出明确错误而不是伪造内容。
 *
 * 兼容出口: `import t from "@/lib/i18n"` 继续返回 zh-CN 字典(默认语言),
 * 全站既有 import 不变、页面输出不变。
 */

import type { Dictionary } from "./locales/zh-CN";
import zhCN from "./locales/zh-CN";
import en from "./locales/en";
import ja from "./locales/ja";
import ko from "./locales/ko";
import de from "./locales/de";
import { FALLBACK_LOCALE, isSupportedLocale, type Locale } from "./locales";
export { SUPPORTED_LOCALES, FALLBACK_LOCALE, isSupportedLocale } from "./locales";
export type { Locale } from "./locales";

/** 已注册完整字典的 locale → 字典。五种语言全部就绪。 */
const DICTIONARIES: Partial<Record<Locale, Dictionary>> = {
  "zh-CN": zhCN,
  "en": en,
  "ja": ja,
  "ko": ko,
  "de": de,
};

/**
 * 按 locale 获取字典。
 *
 * - 已注册 locale → 返回其完整字典
 * - 支持(列入 SUPPORTED_LOCALES)但字典未注册(现阶段 en/ja/ko/de) → 抛出
 *   明确错误: 不伪造、不静默回中文(fallback 语义是"回 en", en 本身未备齐)
 * - 未知 locale → 按架构规则回 FALLBACK_LOCALE(en) 处理, 同样抛出上述错误
 *
 * 待 en 字典补齐后, 本函数即为路由层 [locale] 段的取字典入口。
 */
export function getDictionary(locale: string): Dictionary {
  const normalized = isSupportedLocale(locale) ? locale : FALLBACK_LOCALE;
  const dict = DICTIONARIES[normalized];
  if (!dict) {
    throw new Error(
      `i18n: locale "${locale}" 的字典尚未注册(受支持 locale 应全部注册; 缺 ${normalized})`,
    );
  }
  return dict;
}

/** 默认语言(zh-CN)——兼容既有 `import t from "@/lib/i18n"`。 */
export default zhCN;
