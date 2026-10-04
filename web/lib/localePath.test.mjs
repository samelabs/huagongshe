// withLocale() locale-aware 路径 helper 测试
// 运行: npx tsx --test lib/localePath.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { withLocale } from "./localePath.ts";

test("普通公开路径加 locale 前缀", () => {
  assert.equal(withLocale("/search", "ja"), "/ja/search");
  assert.equal(withLocale("/guide", "de"), "/de/guide");
  assert.equal(withLocale("/login", "en"), "/en/login");
  assert.equal(withLocale("/chemical/123", "ko"), "/ko/chemical/123");
  assert.equal(withLocale("/user/amy", "zh-CN"), "/zh-CN/user/amy");
});

test("根路径", () => {
  assert.equal(withLocale("/", "ja"), "/ja");
  assert.equal(withLocale("/", "en"), "/en");
});

test("query string 保留", () => {
  assert.equal(withLocale("/search?q=aspirin", "de"), "/de/search?q=aspirin");
});

test("外部 URL 不处理", () => {
  assert.equal(withLocale("https://huagongshe.com/mcp", "ja"), "https://huagongshe.com/mcp");
  assert.equal(withLocale("mailto:mail@huagongshe.com", "ja"), "mailto:mail@huagongshe.com");
  assert.equal(withLocale("//cdn.example.com/x", "ja"), "//cdn.example.com/x");
});

test("/api /mcp /samelabs /.well-known /_next 不加 locale", () => {
  assert.equal(withLocale("/api/agent-guide", "ja"), "/api/agent-guide");
  assert.equal(withLocale("/mcp", "ja"), "/mcp");
  assert.equal(withLocale("/samelabs/users", "ja"), "/samelabs/users");
  assert.equal(withLocale("/.well-known/acme", "ja"), "/.well-known/acme");
  assert.equal(withLocale("/_next/static/x.js", "ja"), "/_next/static/x.js");
});

test("带扩展名的静态资源不加 locale", () => {
  assert.equal(withLocale("/logo.png", "ja"), "/logo.png");
  assert.equal(withLocale("/docs/paper.pdf", "ja"), "/docs/paper.pdf");
});

test("已带 locale 前缀的路径幂等(不二次叠加)", () => {
  assert.equal(withLocale("/ja/search", "ja"), "/ja/search");
  assert.equal(withLocale("/de/search", "ja"), "/de/search"); // 已有前缀(即使不同)也不叠
});

test("相对路径与锚点不处理", () => {
  assert.equal(withLocale("search", "ja"), "search");
  assert.equal(withLocale("#top", "ja"), "#top");
});
