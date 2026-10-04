/**
 * 公开站单一 locale 常量 · formatter / 名称解析的统一来源
 *
 * 使用: Intl.NumberFormat(SITE_LOCALE)、date.toLocaleDateString(SITE_LOCALE)。
 * 当前值 zh-CN(站点唯一语言包, 见 lib/i18n.ts); 动态 locale 接线时只改这里
 * 的消费方式, 不在各组件重新散落字面量。
 *
 * /samelabs/* 内管面板不消费本常量(维持自带 zh-CN 字面量)。
 */

export const SITE_LOCALE = "zh-CN";
