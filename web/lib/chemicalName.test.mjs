/**
 * 化合物显示名称唯一解析规则（lib/chemicalName.ts 真实实现，tsx 直接加载）：
 * locale → 本地化名 → 英文常用名 → 系统名 → 分子式 → HCID。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const req = createRequire(import.meta.url);
const { resolveChemicalName, SITE_LOCALE } = req("./chemicalName.ts");

const label = (id) => `HCID ${id}`;
const resolve = (chem, locale) => resolveChemicalName(chem, label, locale);
const titleSource = (r) => [r.title, r.source];

test("中文站：本地化名为主标题，英文名作副标题", () => {
  const r = resolve({ id: 1, name_cn: "乙醇", preferred_name: "Ethanol", iupac_name: "ethanol", molecular_formula: "C2H6O" }, "zh-CN");
  assert.deepEqual([r.title, r.secondary, r.source], ["乙醇", "Ethanol", "name_cn"]);
});

test("主标题就是英文名时不重复副标题", () => {
  const r = resolve({ id: 2, preferred_name: "Ethanol" }, "zh-CN");
  assert.deepEqual(titleSource(r), ["Ethanol", "preferred_name"]);
  assert.equal(r.secondary, null);
});

test("依次回落到系统名、分子式、HCID", () => {
  assert.deepEqual(titleSource(resolve({ id: 3, iupac_name: "oxalonitrile", molecular_formula: "C2N2" }, "zh-CN")), ["oxalonitrile", "iupac_name"]);
  assert.deepEqual(titleSource(resolve({ id: 4, molecular_formula: "C2N2" }, "zh-CN")), ["C2N2", "molecular_formula"]);
  assert.deepEqual(titleSource(resolve({ id: 5 }, "zh-CN")), ["HCID 5", "hcid"]);
});

test("非中文 locale 用英文名，不带副标题", () => {
  for (const locale of ["ja-JP", "en-US"]) {
    const r = resolve({ id: 6, name_cn: "乙醇", preferred_name: "Ethanol" }, locale);
    assert.deepEqual(titleSource(r), ["Ethanol", "preferred_name"], locale);
    assert.equal(r.secondary, null, locale);
  }
});

test("空白本地化名不顶替，与英文同串时不重复展示", () => {
  assert.deepEqual(titleSource(resolve({ id: 8, name_cn: "   ", preferred_name: "Cyanogen" }, "zh-CN")), ["Cyanogen", "preferred_name"]);
  const same = resolve({ id: 9, name_cn: "Cyanogen", preferred_name: "Cyanogen" }, "zh-CN");
  assert.equal(same.title, "Cyanogen");
  assert.equal(same.secondary, null);
});

test("中文站无英文名时以系统名作副标题", () => {
  const r = resolve({ id: 10, name_cn: "乙醇", iupac_name: "ethanol", molecular_formula: "C2H6O" }, "zh-CN");
  assert.deepEqual([r.title, r.secondary, r.source], ["乙醇", "ethanol", "name_cn"]);
});

test("站点默认 locale 为 zh-CN", () => {
  assert.equal(SITE_LOCALE, "zh-CN");
});
