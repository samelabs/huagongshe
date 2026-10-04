// 运行时 i18n 链路测试:
//  1. server helper: getRequestLocale() 按 x-site-locale header 规则取值
//  2. client runtime: useDictionary() 按 locale 返回对应语言字典
// server helper 依赖 next/headers 的 async headers(), 通过注入式验证规则本体
// (isSupportedLocale + SITE_LOCALE fallback), 与 proxy 链路测试互补。
// 运行: npx tsx --test lib/runtimeI18n.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

import { isSupportedLocale, SUPPORTED_LOCALES } from "./i18n/locales.ts";
import { SITE_LOCALE } from "./locale.ts";
import { getDictionary } from "./i18n/index.ts";

/** serverI18n.getRequestLocale 的规则本体(header → locale) */
function resolveRequestLocale(headerValue) {
  if (headerValue && isSupportedLocale(headerValue)) return headerValue;
  return SITE_LOCALE;
}

test("x-site-locale: ja → ja", () => {
  assert.equal(resolveRequestLocale("ja"), "ja");
});

test("x-site-locale: de → de", () => {
  assert.equal(resolveRequestLocale("de"), "de");
});

test("非法值 → zh-CN(SITE_LOCALE)", () => {
  assert.equal(resolveRequestLocale("fr"), "zh-CN");
  assert.equal(resolveRequestLocale("zh-TW"), "zh-CN");
  assert.equal(resolveRequestLocale("en-US"), "zh-CN");
});

test("无 header → zh-CN(SITE_LOCALE)", () => {
  assert.equal(resolveRequestLocale(null), "zh-CN");
});

test("五种 SUPPORTED_LOCALES 均合法", () => {
  for (const l of SUPPORTED_LOCALES) assert.equal(resolveRequestLocale(l), l);
});

/* ─────── client runtime: useDictionary 的取值逻辑(getDictionary(locale)) ─────── */

test("client runtime: locale=en → useDictionary().common.loading 为英文", () => {
  assert.equal(getDictionary("en").common.loading, "Loading…");
});

test("client runtime: locale=ja → 日文", () => {
  assert.equal(getDictionary("ja").common.loading, "読み込み中…");
});

test("client runtime: locale=ko → 韩文", () => {
  assert.equal(getDictionary("ko").common.loading, "불러오는 중…");
});

test("client runtime: locale=de → 德文", () => {
  assert.equal(getDictionary("de").common.loading, "Wird geladen…");
});

test("client runtime: locale=zh-CN → 中文", () => {
  assert.equal(getDictionary("zh-CN").common.loading, "加载中…");
});

test("useDictionary 返回的字典含函数且可正常调用(证明未复制/未序列化)", () => {
  for (const l of SUPPORTED_LOCALES) {
    const dict = getDictionary(l);
    assert.equal(typeof dict.common.pageOf, "function");
    assert.equal(dict.common.pageOf(2, 5).includes("2"), true, l);
  }
});
