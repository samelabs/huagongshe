import assert from "node:assert/strict";
import { test } from "node:test";

/** 管理端列表分页纯函数：直接测 lib/adminPagination.ts 真实实现。 */
const { PAGE_SIZE, parseAdminPage, adminOffset, adminTotalPages } = await import("./adminPagination.ts");

test("每页 50 条", () => {
  assert.equal(PAGE_SIZE, 50);
});

test("合法 page 原样解析，缺省为 1", () => {
  assert.deepEqual([null, "", "1", "2", "10"].map(parseAdminPage), [1, 1, 1, 2, 10]);
});

test("非法 page 一律按 1 处理", () => {
  const bad = ["0", "-1", "abc", "1.5", "1e2", " 2", "NaN", "Infinity"];
  assert.deepEqual(bad.map(parseAdminPage), bad.map(() => 1));
});

test("1-based page 换算 offset", () => {
  assert.deepEqual([adminOffset(1), adminOffset(2), adminOffset(10), adminOffset(1, 25), adminOffset(2, 25)],
    [0, 50, 450, 0, 25]);
});

test("总页数至少为 1，按页长向上取整", () => {
  assert.deepEqual([0, 1, 50, 51, 480, 500, 501].map((n) => adminTotalPages(n)), [1, 1, 1, 2, 10, 10, 11]);
});
