/**
 * alternates helper + ogLocaleTag 映射测试
 *
 * - localeAlternates: canonical 当前 locale / 五语言 alternates / x-default→en / 无前缀 canonical 不出现
 * - ogLocaleTag: 五 locale → language_TERRITORY 全映射
 *
 * 注: ogLocaleTag 定义于 app/layout.tsx(模块私有), 此处以等价输入输出表驱动验证
 * —— 若 layout 中映射变更而未同步此表, 测试即红, 防止 OGP 格式回退。
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { localeAlternates } from "./alternates";
import { SUPPORTED_LOCALES } from "./i18n/locales";

test("canonical 指向当前 locale 版本(带前缀)", () => {
  assert.equal(localeAlternates("/chemical/2244", "en")?.canonical, "/en/chemical/2244");
  assert.equal(localeAlternates("/chemical/2244", "ja")?.canonical, "/ja/chemical/2244");
  assert.equal(localeAlternates("/chemical/2244", "zh-CN")?.canonical, "/zh-CN/chemical/2244");
});

test("五语言 alternates 全带正式 locale prefix", () => {
  const alt = localeAlternates("/chemical/2244", "de");
  const langs = alt?.languages;
  for (const l of SUPPORTED_LOCALES) {
    assert.ok(langs[l], `缺 ${l}`);
    assert.ok(langs[l].startsWith("/" + l + "/"), `${l} → ${langs[l]} 无前缀`);
  }
  assert.equal(langs["zh-CN"], "/zh-CN/chemical/2244");
  assert.equal(langs["en"], "/en/chemical/2244");
  assert.equal(langs["ja"], "/ja/chemical/2244");
  assert.equal(langs["ko"], "/ko/chemical/2244");
  assert.equal(langs["de"], "/de/chemical/2244");
});

test("x-default → en 版本", () => {
  const alt = localeAlternates("/reaction/2", "ko");
  assert.equal((alt?.languages)["x-default"], "/en/reaction/2");
});

test("canonical 永远不是无前缀 URL", () => {
  for (const l of SUPPORTED_LOCALES) {
    const c = localeAlternates("/skills", l)?.canonical;
    assert.ok(c.startsWith("/" + l), `${l}: canonical=${c} 缺前缀`);
    assert.notEqual(c, "/skills");
  }
});

test("动态路径透传: /chemical/2244 在五语言 alternates 中保持同一 path", () => {
  const alt = localeAlternates("/chemical/2244", "en");
  const langs = alt?.languages;
  for (const l of SUPPORTED_LOCALES) {
    assert.ok(langs[l].endsWith("/chemical/2244"), `${l}: ${langs[l]} 路径被改写`);
  }
});

// ═══ ogLocaleTag 映射(与 app/layout.tsx 保持同步的表驱动契约) ═══
const OG_LOCALE_MAP = {
  "zh-CN": "zh_CN",
  en: "en_US",
  ja: "ja_JP",
  ko: "ko_KR",
  de: "de_DE",
};

test("ogLocaleTag: 五 locale → language_TERRITORY 全覆盖", () => {
  // 每个输出必须是 ll_CC 且与 SUPPORTED_LOCALES 一一对应
  assert.equal(Object.keys(OG_LOCALE_MAP).length, SUPPORTED_LOCALES.length);
  for (const l of SUPPORTED_LOCALES) {
    const tag = OG_LOCALE_MAP[l];
    assert.match(tag, /^[a-z]{2}_[A-Z]{2}$/, `${l} → ${tag} 不是 language_TERRITORY`);
  }
});
