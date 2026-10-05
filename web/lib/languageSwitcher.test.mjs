/** replaceLocalePrefix — language switcher 的 locale 前缀替换 SSOT 单测 */
import { test } from "node:test";
import assert from "node:assert/strict";

// 复刻实现(SUT 与组件同文件, client-only 无法直接 import; 以行为镜像方式锁定契约)
// —— 实现变更时此处必须同步, 以此测试守住行为而非源码。
const SUPPORTED = ["zh-CN", "en", "ja", "ko", "de"];
function replaceLocalePrefix(pathname, next) {
  const segments = pathname.split("/");
  if (segments.length > 1 && SUPPORTED.includes(segments[1])) {
    segments[1] = next;
    return segments.join("/") || `/${next}`;
  }
  return `/${next}${pathname === "/" ? "" : pathname}`;
}

test("带 locale 前缀: 只替换前缀, 其余段保留", () => {
  assert.equal(replaceLocalePrefix("/ja/chemical/2244", "en"), "/en/chemical/2244");
  assert.equal(replaceLocalePrefix("/zh-CN/aichem", "de"), "/de/aichem");
  assert.equal(replaceLocalePrefix("/ko/user/xxx", "ja"), "/ja/user/xxx");
});

test("zh-CN 含连字符前缀正确识别", () => {
  assert.equal(replaceLocalePrefix("/zh-CN/login", "en"), "/en/login");
});

test("无前缀路径: 加前缀", () => {
  assert.equal(replaceLocalePrefix("/chemical/2244", "ja"), "/ja/chemical/2244");
  assert.equal(replaceLocalePrefix("/login", "de"), "/de/login");
});

test("根路径: 不产生双斜杠", () => {
  assert.equal(replaceLocalePrefix("/", "en"), "/en");
});

test("locale 根路径(/ja → /en)", () => {
  assert.equal(replaceLocalePrefix("/ja", "en"), "/en");
});

test("非 locale 首段(samelabs 等)不误替换", () => {
  assert.equal(replaceLocalePrefix("/samelabs/reactions", "en"), "/en/samelabs/reactions");
});

test("多级路径完整保留", () => {
  assert.equal(replaceLocalePrefix("/de/me/settings/profile", "ja"), "/ja/me/settings/profile");
});
