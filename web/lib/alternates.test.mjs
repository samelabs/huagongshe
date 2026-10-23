/**
 * alternates helper 真实 SUT 测试
 *
 * - chemicalAlternates: 化合物页 canonical 当前 locale / 五语言 hreflang / x-default→en
 * - localeCanonical: 隐性多语言页只有自引用 canonical, 不出现 hreflang 集合
 * - ogLocaleTag: 直接 import 真实实现验证五 locale 映射(不维护镜像映射表)
 * - localizedAbsoluteUrl: SITE_ORIGIN + withLocale 组合
 *
 * 运行(tsx 已声明为 dev dependency, 统一入口 `npm run test:locale`,
 * tsx --test 直接加载真实 .ts SUT, 不再使用 tsc 临时编译到 /tmp 的人工协议):
 *   npx tsx --test lib/alternates.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const req = createRequire(import.meta.url);
const { chemicalAlternates, localeCanonical, ogLocaleTag, localizedAbsoluteUrl, SITE_ORIGIN } = req("./alternates.ts");
const { SUPPORTED_LOCALES } = req("./i18n/locales.ts");

test("化合物 canonical 指向当前 locale 版本(带前缀)", () => {
  assert.equal(chemicalAlternates(2244, "en")?.canonical, "/en/chemical/2244");
  assert.equal(chemicalAlternates("2244", "ja")?.canonical, "/ja/chemical/2244");
  assert.equal(chemicalAlternates(2244, "zh-CN")?.canonical, "/zh-CN/chemical/2244");
});

test("化合物五语言 hreflang 全带正式 locale prefix 且同一 path", () => {
  const langs = chemicalAlternates(2244, "de")?.languages;
  for (const l of SUPPORTED_LOCALES) {
    assert.equal(langs[l], `/${l}/chemical/2244`, `${l} → ${langs[l]}`);
  }
});

test("化合物 x-default → en 版本", () => {
  assert.equal((chemicalAlternates(2, "ko")?.languages)["x-default"], "/en/chemical/2");
});

test("隐性多语言页: 只有自引用 canonical, 没有 hreflang 集合", () => {
  for (const l of SUPPORTED_LOCALES) {
    for (const path of ["/", "/reaction/2", "/note/abc1234", "/skills"]) {
      const alt = localeCanonical(path, l);
      assert.deepEqual(Object.keys(alt), ["canonical"]);
      assert.ok(alt.canonical.startsWith("/" + l), `${l}: canonical=${alt.canonical} 缺前缀`);
    }
  }
  assert.equal(localeCanonical("/reaction/2", "ja").canonical, "/ja/reaction/2");
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
