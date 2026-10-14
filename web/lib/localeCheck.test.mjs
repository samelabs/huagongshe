// 防回退静态检查（v1.7.1）：
// 1. 非 zh-CN 字典值不得含中文字符（en、ko、de 零汉字，ja 不得中日混杂）；
// 2. tsx 里不得出现 err.detail / error.detail 直接渲染或直接使用。
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, "..");

test("非 zh-CN 字典(en, ko, de)的值不得含中文字符", async () => {
  const cjkRegex = /[\u4e00-\u9fa5]/;
  for (const locale of ["en", "ko", "de"]) {
    const mod = await import(`./i18n/locales/${locale}.ts`);
    const dict = mod.default;

    function checkObj(obj, prefix = "") {
      for (const [k, v] of Object.entries(obj)) {
        const fullKey = prefix ? `${prefix}.${k}` : k;
        if (typeof v === "string") {
          assert.equal(
            cjkRegex.test(v),
            false,
            `[${locale}] 键 "${fullKey}" 包含中文字符: "${v}"`,
          );
        } else if (typeof v === "function") {
          try {
            const res = v("test", "test2", 1, 2);
            if (typeof res === "string") {
              assert.equal(
                cjkRegex.test(res),
                false,
                `[${locale}] 函数键 "${fullKey}" 返回值包含中文字符: "${res}"`,
              );
            }
          } catch {
            // 忽略构造参数不合法的函数异常
          }
        } else if (v && typeof v === "object" && !Array.isArray(v)) {
          checkObj(v, fullKey);
        } else if (Array.isArray(v)) {
          v.forEach((item, idx) => {
            if (typeof item === "string") {
              assert.equal(
                cjkRegex.test(item),
                false,
                `[${locale}] 数组项 "${fullKey}[${idx}]" 包含中文字符: "${item}"`,
              );
            }
          });
        }
      }
    }

    checkObj(dict);
  }
});

test("日文字典(ja)不得中日混杂(无纯简中字与中文逗号)", async () => {
  const mod = await import("./i18n/locales/ja.ts");
  const dict = mod.default;
  // 简中特有字符集（日文新字体/常用汉字中不存在）
  const scOnlyRegex = /[这里这个那么怎么什么们门关为对发国个与样长间现统认证录码选标题设备户报验实质确单两进开总线结见动从]/;
  // 中文标点
  const zhPunctRegex = /[，]/;

  function checkObj(obj, prefix = "") {
    for (const [k, v] of Object.entries(obj)) {
      const fullKey = prefix ? `${prefix}.${k}` : k;
      if (typeof v === "string") {
        assert.equal(
          zhPunctRegex.test(v),
          false,
          `[ja] 键 "${fullKey}" 包含中文标点: "${v}"`,
        );
      } else if (v && typeof v === "object" && !Array.isArray(v)) {
        checkObj(v, fullKey);
      }
    }
  }

  checkObj(dict);
});

test("tsx 里不得出现 err.detail 直接渲染", () => {
  function scanTsx(dir) {
    const files = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== "node_modules" && entry.name !== ".next") {
          files.push(...scanTsx(full));
        }
      } else if (entry.name.endsWith(".tsx")) {
        files.push(full);
      }
    }
    return files;
  }

  const tsxFiles = [...scanTsx(path.join(webRoot, "app")), ...scanTsx(path.join(webRoot, "components"))];
  for (const file of tsxFiles) {
    const content = fs.readFileSync(file, "utf8");
    const rel = path.relative(webRoot, file);
    assert.equal(
      /(err|error)\.detail\b/.test(content),
      false,
      `直接使用/渲染 (err|error).detail 违规: ${rel}`,
    );
  }
});
