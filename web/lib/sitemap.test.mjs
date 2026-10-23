/**
 * app/sitemap.ts 真实实现测试（tsx 直接加载 .ts）：
 * 只收录公开、可索引、有独立 canonical 的入口页，五语言各一份。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const req = createRequire(import.meta.url);
const { default: sitemap, SITEMAP_URL } = req("../app/sitemap.ts");
const { SITE_ORIGIN } = req("./alternates.ts");
const { SUPPORTED_LOCALES } = req("./i18n/locales.ts");

const ENTRY_PATHS = ["/", "/search", "/guide", "/mcp-guide"];
const entries = sitemap();
const urls = entries.map((e) => e.url);

test("入口页 × 五语言，URL 不重复", () => {
  assert.deepEqual(SUPPORTED_LOCALES, ["zh-CN", "en", "ja", "ko", "de"]);
  assert.equal(urls.length, ENTRY_PATHS.length * SUPPORTED_LOCALES.length);
  assert.equal(new Set(urls).size, urls.length);
});

test("URL 全部来自入口白名单与站点 origin（en 同样带前缀）", () => {
  const allowed = new Set(SUPPORTED_LOCALES.flatMap((loc) =>
    ENTRY_PATHS.map((p) => (p === "/" ? `${SITE_ORIGIN}/${loc}` : `${SITE_ORIGIN}/${loc}${p}`))));
  assert.deepEqual(new Set(urls), allowed);
});

test("不收录条款/隐私/支持、登录后页面、动态实体页与参数化检索", () => {
  const forbidden = ["/terms", "/privacy", "/support", "/skills", "/aichem", "/login", "/me", "/samelabs",
    "/api/", "/note/", "/chemical/", "/reaction/", "/user/", "?q=", "&q=", "page=", "mode="];
  for (const url of urls) for (const token of forbidden) assert.ok(!url.includes(token), `${token} in ${url}`);
});

test("每条只有 url，不伪造 lastModified 等字段", () => {
  for (const e of entries) assert.deepEqual(Object.keys(e), ["url"]);
});

test("robots 从同一来源声明 sitemap 地址", () => {
  assert.ok(SITEMAP_URL.startsWith(SITE_ORIGIN));
  const robots = readFileSync(new URL("../app/robots.ts", import.meta.url), "utf-8");
  assert.ok(robots.includes("sitemap: SITEMAP_URL"));
  assert.ok(robots.includes('import { SITEMAP_URL } from "./sitemap"'));
});
