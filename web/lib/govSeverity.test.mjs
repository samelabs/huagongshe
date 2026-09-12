/* 治理严重度: 结构化状态 → 颜色类 的判定测试 (纯 ESM, 不在 tsconfig include 内, 不参与构建)。
   运行: cd web && node --test lib/govSeverity.test.mjs */
import test from "node:test";
import assert from "node:assert/strict";
import { severityClass, statusFromCount, statusFromSection } from "./govSeverity.ts";

test("严重度 × active → 颜色类 (验收五项)", () => {
  assert.equal(severityClass("高", true), "bad");    // 高 + >0
  assert.equal(severityClass("高", false), "quiet"); // 高 + 0
  assert.equal(severityClass("中", true), "warn");   // 中 + >0
  assert.equal(severityClass("中", false), "quiet"); // 中 + 0
  assert.equal(severityClass("低", false), "quiet"); // unavailable → quiet
});

test("低严重度沿用既有映射(非高 → warn), 仅在 active 时着色", () => {
  assert.equal(severityClass("低", true), "warn");
});

test("exact 数值: value>0 才是真实异常", () => {
  assert.deepEqual(statusFromSection({ available: true, mode: "exact", value: 42 }), { available: true, active: true });
  assert.deepEqual(statusFromSection({ available: true, mode: "exact", value: 0 }), { available: true, active: false });
});

test("sample: 只看 matched, 不看格式化字符串", () => {
  const hit = statusFromSection({ available: true, mode: "sample", value: { exact: false, sample_size: 3000, matched: 42, ratio: 0.014 } });
  const zero = statusFromSection({ available: true, mode: "sample", value: { exact: false, sample_size: 3000, matched: 0, ratio: 0 } });
  assert.deepEqual(hit, { available: true, active: true });
  assert.deepEqual(zero, { available: true, active: false });
});

test("unavailable / deferred / 缺载荷 → active=false", () => {
  assert.deepEqual(statusFromSection({ available: false, mode: "exact", value: null }), { available: false, active: false });
  assert.deepEqual(statusFromSection({ available: true, mode: "deferred", value: 0 }), { available: false, active: false });
  assert.deepEqual(statusFromSection(null), { available: false, active: false });
  assert.deepEqual(statusFromSection({ available: true, mode: "exact", value: null }), { available: true, active: false });
});

test("section 缺失(unavailable) 与 0 不可混淆", () => {
  const unavailable = statusFromSection({ available: false, mode: "error", value: null });
  const zero = statusFromSection({ available: true, mode: "sample", value: { matched: 0, sample_size: 3000 } });
  assert.equal(unavailable.active, false);
  assert.equal(zero.active, false);
  assert.notEqual(unavailable.available, zero.available);
});

test("exact 计数助手(seed / identity 悬案): 只有数字才判定", () => {
  assert.deepEqual(statusFromCount(7), { available: true, active: true });
  assert.deepEqual(statusFromCount(0), { available: true, active: false });
  assert.deepEqual(statusFromCount(null), { available: false, active: false });
  assert.deepEqual(statusFromCount("0"), { available: false, active: false });
});
