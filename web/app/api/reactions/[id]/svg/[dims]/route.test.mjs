/* D002 — 反应 SVG BFF Cache-Control 契约测试 (纯 node:test, 不在 tsconfig include 内)。
   运行: cd web && node --test --experimental-strip-types \
     "app/api/reactions/[id]/svg/[dims]/route.test.mjs"
   通过 --experimental-strip-types + import ../route.ts 直调真实 GET handler;
   global fetch 以替身覆盖模拟 upstream(不改 production 代码)。 */
import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";
import { pathToFileURL } from "node:url";

register(pathToFileURL("./_d002_next_alias.mjs"), pathToFileURL("./"));

const mod = await import("./route.ts");
const GET = mod.GET;

const REAL_FETCH = globalThis.fetch;

function upstreamResponse(headers) {
  // Headers(undefined) → 空; 与真实 Response 对齐
  return new Response("<svg>ok</svg>", {
    status: 200,
    headers: { "content-type": "image/svg+xml", ...headers },
  });
}

function makeCtx(id, dims) {
  return { params: Promise.resolve({ id, dims }) };
}

function makeRequest() {
  return new Request("http://localhost/api/reactions/1/svg/300x120.svg");
}

async function withUpstream(upstream, fn) {
  const captured = {};
  globalThis.fetch = async (url, init) => {
    captured.url = url;
    captured.init = init;
    return typeof upstream === "function" ? upstream() : upstream;
  };
  try {
    return { result: await fn(), captured };
  } finally {
    globalThis.fetch = REAL_FETCH;
  }
}

test("§10 public 200: passthrough upstream Cache-Control(300s), 无 31536000/immutable", async () => {
  const { result } = await withUpstream(
    () => upstreamResponse({ "cache-control": "public, max-age=300" }),
    () => GET(makeRequest(), makeCtx("1", "300x120.svg")),
  );
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("content-type"), "image/svg+xml");
  assert.equal(result.headers.get("cache-control"), "public, max-age=300");
  assert.ok(!result.headers.get("cache-control").includes("31536000"));
  assert.ok(!result.headers.get("cache-control").includes("immutable"));
  assert.equal(await result.text(), "<svg>ok</svg>");
});

test("§11 upstream 200 缺 Cache-Control → fallback private, no-store(禁 public)", async () => {
  const { result } = await withUpstream(
    () => new Response("<svg/>", { status: 200, headers: { "content-type": "image/svg+xml" } }),
    () => GET(makeRequest(), makeCtx("1", "300x120.svg")),
  );
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("cache-control"), "private, no-store");
});

test("§12 upstream 请求头锁定: 仅 accept: image/svg+xml, 无 Cookie/Authorization; cache:no-store", async () => {
  const { captured } = await withUpstream(
    () => upstreamResponse({ "cache-control": "public, max-age=300" }),
    () => GET(makeRequest(), makeCtx("1", "300x120.svg")),
  );
  assert.equal(captured.init.cache, "no-store");
  assert.deepEqual(captured.init.headers, { accept: "image/svg+xml" });
  const headerKeys = Object.keys(captured.init.headers).map((k) => k.toLowerCase());
  assert.ok(!headerKeys.includes("cookie"));
  assert.ok(!headerKeys.includes("authorization"));
  assert.match(captured.url, /\/api\/reactions\/1\/svg\?w=300&h=120$/);
});

test("§13 upstream non-200 → 既有 BFF 404 JSON 契约不变", async () => {
  const { result } = await withUpstream(
    () => new Response("nope", { status: 404 }),
    () => GET(makeRequest(), makeCtx("1", "300x120.svg")),
  );
  assert.equal(result.status, 404);
  assert.deepEqual(await result.json(), { detail: "Not Found" });
});

test("§13b fetch 异常 → 既有 404 行为不变", async () => {
  const { result } = await withUpstream(
    () => { throw new Error("connection refused"); },
    () => GET(makeRequest(), makeCtx("1", "300x120.svg")),
  );
  assert.equal(result.status, 404);
  assert.deepEqual(await result.json(), { detail: "Not Found" });
});

test("§7b 非法 id/dims → 既有 404 不变(fetch 未发生)", async () => {
  let fetched = false;
  const { result } = await withUpstream(
    () => { fetched = true; return upstreamResponse({}); },
    () => GET(makeRequest(), makeCtx("abc", "300x120.svg")),
  );
  assert.equal(result.status, 404);
  assert.equal(fetched, false);
});
