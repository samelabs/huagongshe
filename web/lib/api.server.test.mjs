import assert from "node:assert/strict";
import { test } from "node:test";

/**
 * 服务端取数层转发头规则单测（经 --conditions=react-server 加载，
 * server-only 标记按服务端条件解析为空实现）。
 * 只测纯函数 forwardHeaders 的合并规则——不发真实请求。
 */
const { forwardHeaders } = await import("./api.server.ts");

test("无入站身份时不添加任何头", () => {
  const h = forwardHeaders(undefined, null);
  assert.equal(h.get("x-real-ip"), null);
  assert.equal(h.get("cookie"), null);
});

test("入站 x-real-ip 与 cookie 作为默认身份转发", () => {
  const h = forwardHeaders(undefined, { realIp: "203.0.113.9", cookie: "a=1" });
  assert.equal(h.get("x-real-ip"), "203.0.113.9");
  assert.equal(h.get("cookie"), "a=1");
});

test("调用方显式 cookie 优先于入站 cookie（允许收窄会话 cookie）", () => {
  const h = forwardHeaders({ cookie: "hgs_session=xyz" }, { realIp: "203.0.113.9", cookie: "a=1; hgs_session=xyz; other=2" });
  assert.equal(h.get("cookie"), "hgs_session=xyz");
});

test("x-real-ip 只认入站值——调用方自带的一律被入站值覆盖", () => {
  const h = forwardHeaders({ "x-real-ip": "1.2.3.4" }, { realIp: "203.0.113.9", cookie: null });
  assert.equal(h.get("x-real-ip"), "203.0.113.9");
});

test("入站缺失 realIp 时不产出该头（后端按无 IP 处理）", () => {
  const h = forwardHeaders({ accept: "application/json" }, { realIp: null, cookie: "a=1" });
  assert.equal(h.get("x-real-ip"), null);
  assert.equal(h.get("accept"), "application/json");
});

test("Headers 实例形式的调用方头同样参与合并", () => {
  const h = forwardHeaders(new Headers({ "x-case": "probe" }), { realIp: "203.0.113.9", cookie: null });
  assert.equal(h.get("X-Case"), "probe");
  assert.equal(h.get("x-real-ip"), "203.0.113.9");
});
