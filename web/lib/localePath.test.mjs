// withLocale()/stripLocalePrefix()/isPathAtOrBelow()/applyLocale() locale-aware 路径 helper 测试
// SUT: web/lib/localePath.ts(真实实现, 无镜像)。
// v1.6.0: tsx 已声明为 dev dependency, 统一入口 `npm run test:locale`
// (tsx --test 直接加载真实 .ts SUT, 不再使用 tsc 临时编译到 /tmp 的人工协议):
//   npx tsx --test lib/localePath.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const req = createRequire(import.meta.url);
const { withLocale, stripLocalePrefix, isPathAtOrBelow, splitLocalePrefix, replaceLocalePrefix, applyLocale } = req("./localePath.ts");

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

test("/api /mcp /oauth /samelabs /.well-known /_next 不加 locale", () => {
  assert.equal(withLocale("/api/agent-guide", "ja"), "/api/agent-guide");
  assert.equal(withLocale("/mcp", "ja"), "/mcp");
  assert.equal(withLocale("/oauth/authorize?x=1", "ja"), "/oauth/authorize?x=1");
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

/* ─────── Batch 2: stripLocalePrefix / isPathAtOrBelow / mcp 边界 ─────── */

test("splitLocalePrefix: 唯一 locale 前缀 parser", () => {
  assert.deepEqual(splitLocalePrefix("/ja/aichem"), { locale: "ja", rest: "/aichem" });
  assert.deepEqual(splitLocalePrefix("/en"), { locale: "en", rest: "/" });
  assert.deepEqual(splitLocalePrefix("/en/"), { locale: "en", rest: "/" });
  assert.deepEqual(splitLocalePrefix("/zh-CN/submit"), { locale: "zh-CN", rest: "/submit" });
  assert.equal(splitLocalePrefix("/chemical"), null);
  assert.equal(splitLocalePrefix("/"), null);
});

test("withLocale: query 在 locale 前缀判断之外, 原样保留", () => {
  assert.equal(withLocale("/search?q=x", "ja"), "/ja/search?q=x");
  assert.equal(withLocale("/en/search?q=x", "ja"), "/en/search?q=x");
  assert.equal(withLocale("/api/health?token=1", "ja"), "/api/health?token=1");
  assert.equal(withLocale("/mcp?q=1", "ja"), "/mcp?q=1");
});

test("replaceLocalePrefix: 只换前缀, 不碰 query 之外的语义", () => {
  assert.equal(replaceLocalePrefix("/ja/chemical/2244", "en"), "/en/chemical/2244");
  assert.equal(replaceLocalePrefix("/", "en"), "/en");
});

test("stripLocalePrefix: 剥离 locale 前缀", () => {
  assert.equal(stripLocalePrefix("/ja/aichem"), "/aichem");
  assert.equal(stripLocalePrefix("/de/me/settings/profile"), "/me/settings/profile");
  assert.equal(stripLocalePrefix("/zh-CN/submit"), "/submit");
  assert.equal(stripLocalePrefix("/en"), "/");
  assert.equal(stripLocalePrefix("/en/"), "/");
  assert.equal(stripLocalePrefix("/chemical/1"), "/chemical/1");
  assert.equal(stripLocalePrefix("/samelabs/users"), "/samelabs/users");
});

test("isPathAtOrBelow: 路径边界语义(等于自身或位于子树)", () => {
  // 正例: 自身与子树
  assert.equal(isPathAtOrBelow("/api", "/api"), true);
  assert.equal(isPathAtOrBelow("/api/x", "/api"), true);
  assert.equal(isPathAtOrBelow("/mcp", "/mcp"), true);
  assert.equal(isPathAtOrBelow("/mcp/x", "/mcp"), true);
  assert.equal(isPathAtOrBelow("/.well-known/x", "/.well-known"), true);
  assert.equal(isPathAtOrBelow("/samelabs/x", "/samelabs"), true);
  // 边界负例: 同前缀字符串不是子树, 不得被前缀排除误伤
  assert.equal(isPathAtOrBelow("/api-guide", "/api"), false);
  assert.equal(isPathAtOrBelow("/mcp-guide", "/mcp"), false);
  assert.equal(isPathAtOrBelow("/samelabs-guide", "/samelabs"), false);
});

test("/mcp 只排除自身与子树, /mcp-guide 正常加 locale", () => {
  assert.equal(withLocale("/mcp", "ja"), "/mcp");
  assert.equal(withLocale("/mcp/x", "ja"), "/mcp/x");
  assert.equal(withLocale("/mcp-guide", "ja"), "/ja/mcp-guide");
});

/* ─────── P1-2: applyLocale — 强制切换到目标 locale(登录回跳契约) ─────── */

test("applyLocale: 已带 locale 前缀的路径替换为当前 locale", () => {
  assert.equal(applyLocale("/ja/aichem", "en"), "/en/aichem");
  assert.equal(applyLocale("/en/search?q=abc", "ko"), "/ko/search?q=abc");
  assert.equal(applyLocale("/ja/search?q=x", "de"), "/de/search?q=x");
});

test("applyLocale: 纯 locale 前缀 /en + ja → /ja", () => {
  assert.equal(applyLocale("/en", "ja"), "/ja");
});

test("applyLocale: 无前缀路径加前缀", () => {
  assert.equal(applyLocale("/aichem", "de"), "/de/aichem");
  assert.equal(applyLocale("/", "ja"), "/ja");
});

test("applyLocale: NON_LOCALIZED_PREFIXES 原样返回", () => {
  assert.equal(applyLocale("/samelabs/users", "ja"), "/samelabs/users");
  assert.equal(applyLocale("/api/health", "ja"), "/api/health");
  assert.equal(applyLocale("/mcp", "ko"), "/mcp");
  assert.equal(applyLocale("/oauth/authorize?x=1", "ko"), "/oauth/authorize?x=1");
  assert.equal(applyLocale("/ja/api/health", "en"), "/api/health");
});

test("applyLocale: 静态文件与外部 URL 原样返回", () => {
  assert.equal(applyLocale("/icon.png", "ja"), "/icon.png");
  assert.equal(applyLocale("/docs/paper.pdf", "ko"), "/docs/paper.pdf");
  assert.equal(applyLocale("https://example.com/x", "ja"), "https://example.com/x");
  assert.equal(applyLocale("#top", "de"), "#top");
});

test("applyLocale: query 完整保留", () => {
  assert.equal(applyLocale("/ja/search?q=x&tab=all", "de"), "/de/search?q=x&tab=all");
});
