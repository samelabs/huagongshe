// 线上 Next 会先删请求头再调用 proxy，本测试成立的前提是 next.config 配置了 skipProxyUrlNormalize。
// proxy.ts 最小单测: 用 Next 官方 testing 工具 (next/experimental/testing/server)
// 的 isRewrite / getRewrittenUrl / getRedirectUrl 验证 rewrite/redirect,
// 不用自建 fetch mock 证明正确性。
// tsx 已声明为 dev dependency, 统一入口 `npm run test:locale`
// (tsx --test 直接加载真实 .ts SUT)。malformed cookie / locale redirect 契约
// 正式进入 CI 回归门禁。
import test from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { isRewrite, getRewrittenUrl, getRedirectUrl } from "next/experimental/testing/server";
import { computeCacheBustingSearchParam } from "next/dist/shared/lib/router/utils/cache-busting-search-param";
import proxyModule from "../proxy.ts";

const proxy = proxyModule.default ?? proxyModule;

const ORIGIN = "https://huagongshe.com";

function nextReq(path, { cookie, al, headers: extraHeaders } = {}) {
  const headers = {};
  if (cookie) headers.cookie = cookie;
  if (al) headers["accept-language"] = al;
  if (extraHeaders) Object.assign(headers, extraHeaders);
  return new NextRequest(ORIGIN + path, { headers });
}

/* ─────── 未带 locale: redirect 行为(完全不变) ─────── */

test("未带 locale: / → 检测语言 redirect", async () => {
  const r = await proxy(nextReq("/"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/");
  assert.match(r.headers.getSetCookie().join("; "), /site_locale=en/);
});

test("未带 locale + cookie=ko → /ko/...", async () => {
  const r = await proxy(nextReq("/", { cookie: "site_locale=ko" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/ko/");
});

test("未带 locale + Accept-Language ja-JP → /ja/...", async () => {
  const r = await proxy(nextReq("/", { al: "ja-JP,ja;q=0.9,en;q=0.8" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/ja/");
});

test("Accept-Language de-DE → /de/...", async () => {
  const r = await proxy(nextReq("/", { al: "de-DE,de;q=0.9" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/de/");
});

test("Accept-Language zh-TW → /zh-CN/...(zh 统一 zh-CN)", async () => {
  const r = await proxy(nextReq("/", { al: "zh-TW,zh;q=0.8" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/zh-CN/");
});

test("无支持语言 → /en/...", async () => {
  const r = await proxy(nextReq("/", { al: "fr-FR,fr;q=0.9" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/");
});

test("cookie 优先于 Accept-Language", async () => {
  const r = await proxy(nextReq("/", { cookie: "site_locale=de", al: "ja-JP" }));
  assert.equal(getRedirectUrl(r), ORIGIN + "/de/");
});

test("pathname 与 query 完整保留: /chemical/123", async () => {
  const r = await proxy(nextReq("/chemical/123"));
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/chemical/123");
});

test("pathname 与 query 完整保留: /search?q=aspirin", async () => {
  const r = await proxy(nextReq("/search?q=aspirin"));
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/search?q=aspirin");
});

/* ─────── 已带 locale: Next 原生 rewrite ─────── */

test("/ja → rewrite 到 /, x-site-locale=ja, 匿名访问可缓存不写 cookie", async () => {
  const r = await proxy(nextReq("/ja"));
  assert.ok(isRewrite(r), "应为 Next rewrite 响应");
  assert.equal(getRewrittenUrl(r), ORIGIN + "/");
  assert.equal(r.headers.getSetCookie().length, 0);
});

test("/ja/chemical/123 → rewrite 到 /chemical/123, x-site-locale=ja 传给内部 route", async () => {
  const r = await proxy(nextReq("/ja/chemical/123"));
  assert.ok(isRewrite(r));
  assert.equal(getRewrittenUrl(r), ORIGIN + "/chemical/123");
  // rewrite 的 request headers 通过 x-middleware-override-headers / x-middleware-request-* 透传
  const override = r.headers.get("x-middleware-override-headers") ?? "";
  assert.ok(override.includes("x-site-locale"), "x-site-locale 应在 override 列表");
  assert.equal(r.headers.get("x-middleware-request-x-site-locale"), "ja");
  assert.equal(r.headers.getSetCookie().length, 0);
});

test("/de/search?q=x → rewrite 到 /search?q=x (query 保留, 匿名不写 cookie)", async () => {
  const r = await proxy(nextReq("/de/search?q=x"));
  assert.ok(isRewrite(r));
  assert.equal(getRewrittenUrl(r), ORIGIN + "/search?q=x");
  assert.equal(r.headers.get("x-middleware-request-x-site-locale"), "de");
  assert.equal(r.headers.getSetCookie().length, 0);
});

test("rewrite 响应状态为 200(非 30x)", async () => {
  const r = await proxy(nextReq("/ja/chemical/123"));
  assert.equal(r.status, 200);
  assert.equal(getRedirectUrl(r), null);
});

/* ─────── 排除路径: 不 redirect/rewrite(undefined) ─────── */

test("排除路径不 redirect/rewrite(undefined)", async () => {
  for (const p of [
    "/api/chemicals",
    "/mcp",
    "/oauth/authorize",
    "/oauth/token",
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
    assert.equal(await proxy(nextReq(p)), undefined, p);
  }
});

/* ─────── Batch 2: /mcp 边界语义 —— /mcp-guide 不再被误伤 ─────── */

test("/mcp 与 /mcp/* 排除, /mcp-guide 不排除(307 locale redirect)", async () => {
  assert.equal(await proxy(nextReq("/mcp")), undefined);
  assert.equal(await proxy(nextReq("/mcp/x")), undefined);
  const r = await proxy(nextReq("/mcp-guide"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/mcp-guide");
});

test("/mcp-guide?x=1 redirect 保留 query", async () => {
  const r = await proxy(nextReq("/mcp-guide?x=1"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/mcp-guide?x=1");
});

test("/ja/mcp-guide rewrite 到 /mcp-guide(locale=ja)", async () => {
  const r = await proxy(nextReq("/ja/mcp-guide"));
  assert.equal(r.status, 200);
  assert.equal(getRewrittenUrl(r), ORIGIN + "/mcp-guide");
});

/* ─────── locale 前缀 + excluded path: 无效 alias, 不 rewrite 到 stripped path ─────── */

test("/ja/mcp、/ja/oauth/*、/ja/api/*、/ja/samelabs/*、/ja/.well-known/* 均不 rewrite(undefined)", async () => {
  for (const p of [
    "/ja/mcp",
    "/ja/mcp/x",
    "/ja/oauth/authorize",
    "/ja/api/health",
    "/ja/samelabs/users",
    "/ja/.well-known/example",
  ]) {
    assert.equal(await proxy(nextReq(p)), undefined, p);
  }
});

/* ─────── P2/: malformed site_locale cookie 不再 500, 正常协商 redirect ─────── */

test("malformed cookie + Accept-Language ja → 307 /ja/(不再 URIError)", async () => {
  const r = await proxy(nextReq("/", { cookie: "site_locale=%E0%A4%A", al: "ja-JP,ja;q=0.9" }));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/ja/");
});

test("malformed cookie + 无支持语言 → 307 /en/", async () => {
  const r = await proxy(nextReq("/chemical/123", { cookie: "site_locale=%E0%A4%A", al: "fr-FR,fr;q=0.9" }));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/en/chemical/123");
});

/* ─────── 匿名访问公开页面边缘缓存契约 ─────── */

test("匿名访问公开页面: public 300s 边缘缓存", async () => {
  for (const p of [
    "/zh-CN",
    "/en/",
    "/ja/search",
    "/zh-CN/chemical/4",
    "/en/reaction/1",
    "/zh-CN/note/2001",
    "/en/user/demo",
    "/en/guide",
    "/ja/mcp-guide",
    "/en/privacy",
    "/en/terms",
    "/en/support",
  ]) {
    const r = await proxy(nextReq(p));
    assert.equal(
      r.headers.get("cache-control"),
      "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
      `路径 ${p} 应获得匿名公开缓存头`,
    );
  }
});

test("非个人化公开页(/zh-CN): 带 hgs_session 依然 public; /skills 登录化后恒 private", async () => {
  for (const p of ["/zh-CN"]) {
    const r = await proxy(nextReq(p, { cookie: "hgs_session=fake_session_token" }));
    assert.equal(
      r.headers.get("cache-control"),
      "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
      `非个人化公开页 ${p} 带会话应获得 public 缓存头`,
    );
    assert.equal(r.headers.getSetCookie().length, 0, `${p} 不得包含任何 Set-Cookie 头`);
    assert.equal(r.headers.get("x-middleware-request-x-site-edge-cache"), "public", `${p} x-site-edge-cache 应为 public`);
  }
});

test("与访问者有关的公开路由: 带 hgs_session → private; 匿名 → public", async () => {
  const viewerScopedPaths = [
    "/ja/chemical/4",
    "/zh-CN/search",
    "/zh-CN/reaction/1",
    "/zh-CN/note/1",
    "/zh-CN/user/abcd",
  ];
  for (const p of viewerScopedPaths) {
    const rAuth = await proxy(nextReq(p, { cookie: "hgs_session=fake_session_token" }));
    assert.equal(rAuth.headers.get("cache-control"), "private, no-store", `带会话访问 ${p} 应为 private, no-store`);
    assert.equal(rAuth.headers.get("x-middleware-request-x-site-edge-cache"), "private", `带会话访问 ${p} x-site-edge-cache 应为 private`);

    const rAnon = await proxy(nextReq(p));
    assert.equal(rAnon.headers.get("cache-control"), "public, max-age=0, s-maxage=300, stale-while-revalidate=86400", `匿名访问 ${p} 应为 public`);
    assert.equal(rAnon.headers.get("x-middleware-request-x-site-edge-cache"), "public", `匿名访问 ${p} x-site-edge-cache 应为 public`);
    assert.equal(rAnon.headers.getSetCookie().length, 0, `匿名访问 ${p} 不得有 Set-Cookie`);
  }
});

test("访问非公开页面(工作台/设置/登录/提交): 保持 private, no-store", async () => {
  for (const p of [
    "/zh-CN/aichem",
    "/en/aichem/notes",
    "/zh-CN/me/settings/profile",
    "/en/login",
    "/zh-CN/submit",
  ]) {
    const r = await proxy(nextReq(p));
    assert.equal(
      r.headers.get("cache-control"),
      "private, no-store",
      `非公开页 ${p} 应为 private, no-store`,
    );
  }
});

test("未带 locale 的 307 redirect 响应: 保持 private, no-store", async () => {
  const r = await proxy(nextReq("/"));
  assert.equal(r.status, 307);
  assert.equal(r.headers.get("cache-control"), "private, no-store");
});

/* ─────── 边缘缓存规则（可缓存响应禁 Set-Cookie、RSC 哈希匹配） ─────── */

test("可缓存的匿名公开响应一定没有 Set-Cookie", async () => {
  for (const p of [
    "/zh-CN",
    "/en/",
    "/ja/search",
    "/zh-CN/chemical/4",
    "/en/reaction/1",
    "/zh-CN/note/2001",
    "/en/user/demo",
    "/en/guide",
    "/ja/mcp-guide",
    "/en/privacy",
    "/en/terms",
    "/en/support",
  ]) {
    const r = await proxy(nextReq(p));
    assert.equal(
      r.headers.getSetCookie().length,
      0,
      `可缓存路径 ${p} 不得包含任何 Set-Cookie 头`,
    );
  }
});

test("不可缓存响应(带登录会话、非公开页)以及 307 跳转正常写 site_locale", async () => {
  // 1. 带登录会话
  const r1 = await proxy(nextReq("/ja/chemical/4", { cookie: "hgs_session=xyz" }));
  assert.match(r1.headers.getSetCookie().join("; "), /site_locale=ja/);

  // 2. 非公开页面
  const r2 = await proxy(nextReq("/zh-CN/submit"));
  assert.match(r2.headers.getSetCookie().join("; "), /site_locale=zh-CN/);

  const r3 = await proxy(nextReq("/en/login"));
  assert.match(r3.headers.getSetCookie().join("; "), /site_locale=en/);

  const r4 = await proxy(nextReq("/de/aichem"));
  assert.match(r4.headers.getSetCookie().join("; "), /site_locale=de/);

  // 3. 未带 locale 的 307 跳转
  const r5 = await proxy(nextReq("/"));
  assert.match(r5.headers.getSetCookie().join("; "), /site_locale=en/);
});

test("/zh-CN/skills 登录化: 任何请求形态恒 private(无公开缓存)", async () => {
  // 1. 用同一个导入函数，根据测试请求头算出正确哈希 —— 即便哈希匹配也 private
  const rscHash = await computeCacheBustingSearchParam(undefined, undefined, undefined, undefined);
  const r1 = await proxy(nextReq(`/zh-CN/skills?_rsc=${rscHash}`, { headers: { rsc: "1" } }));
  assert.equal(r1.headers.get("cache-control"), "private, no-store");
  assert.equal(r1.headers.get("x-middleware-request-x-site-edge-cache"), "private");

  // 2. 带 rsc:1 且 _rsc=zzz (哈希不匹配) → private
  const r2 = await proxy(nextReq("/zh-CN/skills?_rsc=zzz", { headers: { rsc: "1" } }));
  assert.equal(r2.headers.get("cache-control"), "private, no-store");
  assert.equal(r2.headers.get("x-middleware-request-x-site-edge-cache"), "private");

  // 3. 只带 rsc:1 → private (mixed)
  const r3 = await proxy(nextReq("/zh-CN/skills", { headers: { rsc: "1" } }));
  assert.equal(r3.headers.get("cache-control"), "private, no-store");
  assert.equal(r3.headers.get("x-middleware-request-x-site-edge-cache"), "private");

  // 4. 只带 _rsc → private (mixed)
  const r4 = await proxy(nextReq("/zh-CN/skills?_rsc=abc"));
  assert.equal(r4.headers.get("cache-control"), "private, no-store");
  assert.equal(r4.headers.get("x-middleware-request-x-site-edge-cache"), "private");

  // 5. next-router-prefetch:1 加正确哈希 —— /skills 登录化后仍 private
  const prefetchHash = await computeCacheBustingSearchParam("1", undefined, undefined, undefined);
  const r5 = await proxy(nextReq(`/zh-CN/skills?_rsc=${prefetchHash}`, { headers: { "next-router-prefetch": "1" } }));
  assert.equal(r5.headers.get("cache-control"), "private, no-store");
  assert.equal(r5.headers.get("x-middleware-request-x-site-edge-cache"), "private");
});

test("/zh-CN/login 任何情况都是 private", async () => {
  const cases = [
    nextReq("/zh-CN/login"),
    nextReq("/zh-CN/login", { cookie: "hgs_session=xyz" }),
    nextReq("/zh-CN/login?_rsc=abc", { headers: { rsc: "1" } }),
    nextReq("/zh-CN/login", { headers: { rsc: "1" } }),
  ];
  for (const req of cases) {
    const r = await proxy(req);
    assert.equal(r.headers.get("cache-control"), "private, no-store");
    assert.equal(r.headers.get("x-middleware-request-x-site-edge-cache"), "private");
  }
});

test("LOCALE_PATH_HEADER 去掉 _rsc 参数: /zh-CN/aichem?tab=x&_rsc=abc 带 rsc:1", async () => {
  const r = await proxy(nextReq("/zh-CN/aichem?tab=x&_rsc=abc", { headers: { rsc: "1" } }));
  assert.equal(r.headers.get("x-middleware-request-x-site-locale-path"), "/zh-CN/aichem?tab=x");
});

/* ─────── /u/{username} 短地址跳转 ─────── */

test("合法用户名跳转: /u/{username} → 307 到 /{locale}/user/{username}，Cache-Control: private, no-store", async () => {
  const r1 = await proxy(nextReq("/u/alice_01"));
  assert.equal(r1.status, 307);
  assert.equal(getRedirectUrl(r1), ORIGIN + "/en/user/alice_01");
  assert.equal(r1.headers.get("cache-control"), "private, no-store");

  // 带 locale 协商
  const r2 = await proxy(nextReq("/u/bob_99", { cookie: "site_locale=ja" }));
  assert.equal(r2.status, 307);
  assert.equal(getRedirectUrl(r2), ORIGIN + "/ja/user/bob_99");
  assert.equal(r2.headers.get("cache-control"), "private, no-store");

  // query 保留
  const r3 = await proxy(nextReq("/u/charlie?tab=notes", { al: "de-DE" }));
  assert.equal(r3.status, 307);
  assert.equal(getRedirectUrl(r3), ORIGIN + "/de/user/charlie?tab=notes");
});

test("非法用户名渲染站内 404 页: /u/abc, /u/invalid-hyphen, /u, /u/ 交给 Next 404 路由", async () => {
  // 不合规名不再返回空白 body 的裸 404 —— proxy 放行(undefined),
  // 由 Next 按未匹配路由渲染站内 404 页并保留 404 状态
  // 长度 < 4
  const r1 = await proxy(nextReq("/u/abc"));
  assert.equal(r1, undefined);

  // 包含非法字符（连字符）
  const r2 = await proxy(nextReq("/u/invalid-user"));
  assert.equal(r2, undefined);

  // 超过 30 字符
  const r3 = await proxy(nextReq("/u/" + "a".repeat(31)));
  assert.equal(r3, undefined);

  // 根路径 /u 与空用户名 /u/
  const r4 = await proxy(nextReq("/u"));
  assert.equal(r4, undefined);

  const r5 = await proxy(nextReq("/u/"));
  assert.equal(r5, undefined);
});

test("大小写归一: /u/HGS_Demo 307 到小写规范形 /u/hgs_demo", async () => {
  const r = await proxy(nextReq("/u/HGS_Demo"));
  assert.equal(r.status, 307);
  assert.equal(getRedirectUrl(r), ORIGIN + "/u/hgs_demo");
  assert.equal(r.headers.get("cache-control"), "private, no-store");

  // query 保留
  const r2 = await proxy(nextReq("/u/Alice_01?tab=notes"));
  assert.equal(r2.status, 307);
  assert.equal(getRedirectUrl(r2), ORIGIN + "/u/alice_01?tab=notes");
});

test("带 locale 前缀的 /ja/u/x 不当作别名（按现有排除规则 404）", async () => {
  const r1 = await proxy(nextReq("/ja/u/alice_01"));
  assert.equal(r1, undefined, "/ja/u/* 命中排除规则，proxy 返回 undefined 交给 Next 404");

  const r2 = await proxy(nextReq("/zh-CN/u/bad"));
  assert.equal(r2, undefined);
});
