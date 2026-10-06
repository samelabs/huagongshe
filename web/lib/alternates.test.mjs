/**
 * alternates helper 真实 SUT 测试
 *
 * - localeAlternates: canonical 当前 locale / 五语言 alternates / x-default→en / 无前缀 canonical 不出现
 * - ogLocaleTag: 直接 import 真实实现验证五 locale 映射(不维护镜像映射表)
 * - localizedAbsoluteUrl: SITE_ORIGIN + withLocale 组合
 *
 * 运行(v1.6.0: tsx 已声明为 dev dependency, 统一入口 `npm run test:locale`,
 * tsx --test 直接加载真实 .ts SUT, 不再使用 tsc 临时编译到 /tmp 的人工协议):
 *   npx tsx --test lib/alternates.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const req = createRequire(import.meta.url);
const { localeAlternates, ogLocaleTag, localizedAbsoluteUrl, SITE_ORIGIN } = req("./alternates.ts");
const { SUPPORTED_LOCALES } = req("./i18n/locales.ts");

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

// ═══ ogLocaleTag(真实实现, 无镜像表) ═══

test("ogLocaleTag: 五 locale → language_TERRITORY 全映射", () => {
  assert.equal(ogLocaleTag("zh-CN"), "zh_CN");
  assert.equal(ogLocaleTag("en"), "en_US");
  assert.equal(ogLocaleTag("ja"), "ja_JP");
  assert.equal(ogLocaleTag("ko"), "ko_KR");
  assert.equal(ogLocaleTag("de"), "de_DE");
});

// ═══ localizedAbsoluteUrl ═══

test("localizedAbsoluteUrl: SITE_ORIGIN + 正式 locale 前缀", () => {
  assert.equal(localizedAbsoluteUrl("/chemical/71747", "ja"), "https://huagongshe.com/ja/chemical/71747");
  assert.equal(localizedAbsoluteUrl("/reaction/3", "de"), "https://huagongshe.com/de/reaction/3");
  assert.equal(localizedAbsoluteUrl("/chemical/1", "en"), "https://huagongshe.com/en/chemical/1");
  assert.equal(SITE_ORIGIN, "https://huagongshe.com");
});
