/**
 * replaceLocalePrefix — 语言切换器 locale 前缀替换的真实 helper 单测
 *
 * SUT: web/lib/localePath.ts 的 replaceLocalePrefix(自 LanguageSwitcher 迁入,
 * 已删除组件内复制实现)。本文件只含断言, 不复制业务函数。
 *
 * tsx 已声明为 dev dependency, 统一入口 `npm run test:locale`
 * (tsx --test 直接加载真实 .ts SUT, 不再使用 tsc 临时编译到 /tmp 的人工协议):
 * npx tsx --test lib/languageSwitcher.test.mjs
 *
 * 断言装载点: 通过 require("./localePath.ts") 取真实 SUT,
 * 找不到时显式 fail, 禁止静默回退到镜像实现。
 */

const test = (await import("node:test")).test;
const assert = (await import("node:assert/strict")).default;

const { createRequire } = await import("node:module");
const req = createRequire(import.meta.url);

let replaceLocalePrefix;
let rewriteNextParam;
try {
  // tsx 装载下直接加载 .ts 源(真实 SUT)
  ({ replaceLocalePrefix, rewriteNextParam } = req("./localePath.ts"));
} catch {
  ({ replaceLocalePrefix, rewriteNextParam } = await import("./localePath.ts"));
}
if (typeof replaceLocalePrefix !== "function") {
  console.error("FATAL: 未加载到真实 helper(web/lib/localePath.ts 编译产物)。按文件头协议用 tsc 编译到临时目录后运行。");
  process.exit(1);
}

test("带 locale 前缀: 只替换前缀, 其余段保留 (五 locale)", () => {
  assert.equal(replaceLocalePrefix("/ja/chemical/2244", "en"), "/en/chemical/2244");
  assert.equal(replaceLocalePrefix("/zh-CN/aichem", "de"), "/de/aichem");
  assert.equal(replaceLocalePrefix("/ko/user/xxx", "ja"), "/ja/user/xxx");
  assert.equal(replaceLocalePrefix("/en/search", "zh-CN"), "/zh-CN/search");
  assert.equal(replaceLocalePrefix("/de/guide", "ko"), "/ko/guide");
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

// ── 语言切换时 next 回跳参数的前缀同步 ──────────────────
test("rewriteNextParam: next 的 locale 前缀换成目标语言", () => {
  const search = `next=${encodeURIComponent("/zh-CN/me/settings")}`;
  const out = rewriteNextParam(search, "en");
  assert.equal(out, `next=${encodeURIComponent("/en/me/settings")}`);
});

test("rewriteNextParam: 无前缀的 next 补目标前缀", () => {
  assert.equal(rewriteNextParam("next=%2Fsubmit%3Fchemical%3D4", "de"),
    `next=${encodeURIComponent("/de/submit?chemical=4")}`);
});

test("rewriteNextParam: 其余 query 原样保留", () => {
  const out = rewriteNextParam("tab=notes&next=%2Fzh-CN%2Faichem%3Ftab%3Dsearch", "ja");
  const params = new URLSearchParams(out);
  assert.equal(params.get("tab"), "notes");
  assert.equal(params.get("next"), "/ja/aichem?tab=search");
});

test("rewriteNextParam: 外部/异常 next 不动，空 search 返回空", () => {
  assert.equal(rewriteNextParam(`next=${encodeURIComponent("https://evil.example")}`, "en"),
    `next=${encodeURIComponent("https://evil.example")}`);
  assert.equal(rewriteNextParam("", "en"), "");
});

test("多级路径完整保留", () => {
  assert.equal(replaceLocalePrefix("/de/me/settings/profile", "ja"), "/ja/me/settings/profile");
});

test("query suffix 契约: helper 只产 pathname, query 由调用方按当前 useSearchParams 拼接", () => {
  // /en/search?q=aspirin 客户端改 q=benzene 后切 ja → /ja/search?q=benzene
  const search = "q=benzene";
  const suffix = search ? `?${search}` : "";
  assert.equal(replaceLocalePrefix("/en/search", "ja") + suffix, "/ja/search?q=benzene");
  // 无 query 时 suffix 为空
  const empty = "";
  assert.equal(replaceLocalePrefix("/en/search", "ja") + (empty ? `?${empty}` : ""), "/ja/search");
});
