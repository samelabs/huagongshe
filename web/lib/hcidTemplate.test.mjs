// (/)：五语言字典模板不得含多余 $（HCID $${id} 回归钉子）。
// SUT: web/lib/i18n/locales/*.ts（真实实现）。入口 `npm run test:locale`。
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const req = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const LOCALES = ["zh-CN", "en", "ja", "ko", "de"];

for (const locale of LOCALES) {
  const dict = req(`./i18n/locales/${locale}.ts`).default;

  test(`[${locale}] hcidLabel/hridLabel 渲染值不含 "$"`, () => {
    assert.equal(dict.common.hcidLabel(4).includes("$"), false, dict.common.hcidLabel(4));
    assert.equal(dict.common.hridLabel(4).includes("$"), false, dict.common.hridLabel(4));
    assert.match(dict.common.hcidLabel(4), /HCID 4\b/);
  });

  test("[" + locale + "] 源码模板不含多余的 $", () => {
    const source = fs.readFileSync(path.join(here, "i18n", "locales", locale + ".ts"), "utf8");
    // "$${" 在模板字符串里会被当插值，这里用拼接构造
    const dollarTemplate = "$$" + "{";
    assert.equal(source.includes(dollarTemplate), false, locale + " 含 " + dollarTemplate + " 模板（多余 $ 回归）");
    assert.equal(source.includes("HCID $" + "$"), false, locale + " 含 HCID $$ 前缀");
  });
}
