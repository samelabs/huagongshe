// proxy.ts 最小单测: 用 Next 官方 testing 工具 (next/experimental/testing/server)
// 的 isRewrite / getRewrittenUrl / getRedirectUrl 验证 rewrite/redirect,
// 不用自建 fetch mock 证明正确性。
// 注意: tsx 未声明为项目依赖 —— 本文件当前未纳入 CI、未直接执行;
// 本批的真实验证来源是 isolated production server 的真实 proxy 行为,
// CI 接入归后续 CI Gate 批次单独治理。
import test from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { isRewrite, getRewrittenUrl, getRedirectUrl } from "next/experimental/testing/server";
import proxyModule from "../proxy.ts";

const proxy = proxyModule.default ?? proxyModule;

const ORIGIN = "https://huagongshe.com";

function nextReq(path, { cookie, al } = {}) {
  const headers = {};
  if (cookie) headers.cookie = cookie;
  if (al) headers["accept-language"] = al;
  return new NextRequest(ORIGIN + path, { headers });
}

/* ─────── 未带 locale: redirect 行为(完全不变) ─────── */

test("未带 locale: / → 检测语言 redirect", () => {
  const r = proxy(nextReq("/"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/");
  assert.match(r.headers.getSetCookie().join("; "), /site_locale=en/);
});

test("未带 locale + cookie=ko → /ko/...", () => {
  const r = proxy(nextReq("/", { cookie: "site_locale=ko" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/ko/");
});

test("未带 locale + Accept-Language ja-JP → /ja/...", () => {
  const r = proxy(nextReq("/", { al: "ja-JP,ja;q=0.9,en;q=0.8" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/ja/");
});

test("Accept-Language de-DE → /de/...", () => {
  const r = proxy(nextReq("/", { al: "de-DE,de;q=0.9" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/de/");
});

test("Accept-Language zh-TW → /zh-CN/...(zh 统一 zh-CN)", () => {
  const r = proxy(nextReq("/", { al: "zh-TW,zh;q=0.8" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/zh-CN/");
});

test("无支持语言 → /en/...", () => {
  const r = proxy(nextReq("/", { al: "fr-FR,fr;q=0.9" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/");
});

test("cookie 优先于 Accept-Language", () => {
  const r = proxy(nextReq("/", { cookie: "site_locale=de", al: "ja-JP" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/de/");
});

test("pathname 与 query 完整保留: /chemical/123", () => {
  const r = proxy(nextReq("/chemical/123"));
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/chemical/123");
});

test("pathname 与 query 完整保留: /search?q=aspirin", () => {
  const r = proxy(nextReq("/search?q=aspirin"));
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/search?q=aspirin");
});

/* ─────── 已带 locale: Next 原生 rewrite ─────── */

test("/ja → rewrite 到 /, x-site-locale=ja, 同步 cookie", () => {
  const r = proxy(nextReq("/ja"));
  assert.ok(isRewrite(r), "应为 Next rewrite 响应");
  assert.equal(getRewrittenUrl(r), ORIGIN + "/");
  assert.match(r.headers.getSetCookie().join("; "), /site_locale=ja/);
});

test("/ja/chemical/123 → rewrite 到 /chemical/123, x-site-locale=ja 传给内部 route", () => {
  const r = proxy(nextReq("/ja/chemical/123"));
  assert.ok(isRewrite(r));
  assert.equal(getRewrittenUrl(r), ORIGIN + "/chemical/123");
  // rewrite 的 request headers 通过 x-middleware-override-headers / x-middleware-request-* 透传
  const override = r.headers.get("x-middleware-override-headers") ?? "";
  assert.ok(override.includes("x-site-locale"), "x-site-locale 应在 override 列表");
  assert.equal(r.headers.get("x-middleware-request-x-site-locale"), "ja");
});

test("/de/search?q=x → rewrite 到 /search?q=x (query 保留)", () => {
  const r = proxy(nextReq("/de/search?q=x"));
  assert.ok(isRewrite(r));
  assert.equal(getRewrittenUrl(r), ORIGIN + "/search?q=x");
  assert.equal(r.headers.get("x-middleware-request-x-site-locale"), "de");
  assert.match(r.headers.getSetCookie().join("; "), /site_locale=de/);
});

test("rewrite 响应状态为 200(非 30x)", () => {
  const r = proxy(nextReq("/ja/chemical/123"));
  assert.equal(r.status, 200);
  assert.equal(getRedirectUrl(r), null);
});

/* ─────── 排除路径: 不 redirect/rewrite(undefined) ─────── */

test("排除路径不 redirect/rewrite(undefined)", () => {
  for (const p of [
    "/api/chemicals",
    "/mcp",
    "/.well-known/acme-challenge/x",
    "/_next/static/chunk.js",
    "/samelabs/dashboard",
    "/favicon.ico",
    "/robots.txt",
    "/sitemap.xml",
    "/manifest.json",
    "/sw.js",
    "/icon.png",
    "/apple-icon.png",
    "/docs/paper.pdf",
  ]) {
    assert.equal(proxy(nextReq(p)), undefined, p);
  }
});

/* ─────── Batch 2: /mcp 边界语义 —— /mcp-guide 不再被误伤 ─────── */

test("/mcp 与 /mcp/* 排除, /mcp-guide 不排除(307 locale redirect)", () => {
  assert.equal(proxy(nextReq("/mcp")), undefined);
  assert.equal(proxy(nextReq("/mcp/x")), undefined);
  const r = proxy(nextReq("/mcp-guide"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/mcp-guide");
});

test("/mcp-guide?x=1 redirect 保留 query", () => {
  const r = proxy(nextReq("/mcp-guide?x=1"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/mcp-guide?x=1");
});

test("/ja/mcp-guide rewrite 到 /mcp-guide(locale=ja)", () => {
  const r = proxy(nextReq("/ja/mcp-guide"));
  assert.equal(r.status, 200);
  assert.equal(getRewrittenUrl(r), ORIGIN + "/mcp-guide");
});
