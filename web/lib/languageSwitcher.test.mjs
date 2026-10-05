/**
 * replaceLocalePrefix — 语言切换器 locale 前缀替换的真实 helper 单测
 *
 * SUT: web/lib/localePath.ts 的 replaceLocalePrefix(自 LanguageSwitcher 迁入,
 * 已删除组件内复制实现)。本文件只含断言, 不复制业务函数。
 *
 * 运行(项目未声明 tsx 依赖, 用本地 tsc 临时编译到 /tmp 后执行):
 *   TMP_DIR="$(mktemp -d)"
 *   ./node_modules/.bin/tsc lib/localePath.ts lib/i18n/locales.ts \
 *     --target ES2022 --module commonjs --moduleResolution node \
 *     --skipLibCheck --outDir "$TMP_DIR" --noEmit false
 *   cp lib/languageSwitcher.test.mjs "$TMP_DIR/" && cd "$TMP_DIR" && node --test languageSwitcher.test.mjs
 *   (完成后删除 $TMP_DIR; tsx 门禁化在 CI Gate 批统一处理)
 *
 * 断言装载点: 编译产物在运行时通过 require("./localePath") 取真实 SUT,
 * 找不到(直接 node 跑源码目录)时显式 fail, 禁止静默回退到镜像实现。
 */

const test = (await import("node:test")).test;
const assert = (await import("node:assert/strict")).default;

const { createRequire } = await import("node:module");
const req = createRequire(import.meta.url);

let replaceLocalePrefix;
try {
  // 编译产物为 CommonJS(见文件头 tsc 协议)
  ({ replaceLocalePrefix } = req("./localePath.js"));
} catch {
  ({ replaceLocalePrefix } = await import("./localePath.js"));
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
