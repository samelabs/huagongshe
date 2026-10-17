#!/usr/bin/env node
/**
 * 取数层静态检查：
 * 1. "use client" 文件不得 import 服务端取数模块 lib/api.server —— 该模块
 *    读请求作用域头（next/headers + server-only），进客户端包即构建破坏。
 * 2. 服务端文件（无 "use client" 的 ts/tsx：page/layout/route/lib）不得从
 *    lib/api 取 apiGet/apiPost/apiPut/apiPatch/apiDelete —— 客户端取数层
 *    不带访客身份直连后端，服务端用它即绕开按 IP 分桶的匿名约束。
 * 纯类型与 URL helper 的引用不受限。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SCAN_DIRS = ["app", "components", "lib"];
const CODE_EXT = /\.(ts|tsx|mjs)$/;
const SELF = new Set(["lib/api.ts", "lib/api.server.ts"]);
const FETCH_FNS = ["apiGet", "apiPost", "apiPut", "apiPatch", "apiDelete"];

const problems = [];

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry.startsWith(".")) continue;
      yield* walk(full);
    } else if (CODE_EXT.test(entry)) {
      yield full;
    }
  }
}

/** import 语句 → { specifier, names }；覆盖 import/import type/动态 import 的静态分析够用形态 */
function* importsOf(src) {
  const re = /import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*["']([^"']+)["']/g;
  let m;
  while ((m = re.exec(src))) {
    yield {
      names: m[1].split(",").map((s) => s.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0]).filter(Boolean),
      specifier: m[2],
    };
  }
}

function resolvesToApiLayer(specifier, fromFile, target) {
  // 别名 "@/lib/api(server)" 或相对路径指向该文件
  if (specifier === `@/${target.replace(/\.ts$/, "")}`) return true;
  if (/^[@A-Za-z]/.test(specifier) && !specifier.startsWith(".")) return false;
  const base = specifier.replace(/\.ts$/, "");
  const resolved = relative(WEB_ROOT, resolve(WEB_ROOT, dirname(fromFile), base));
  return resolved === target.replace(/\.ts$/, "") || resolved === target;
}

for (const dir of SCAN_DIRS) {
  for (const file of walk(join(WEB_ROOT, dir))) {
    const rel = relative(WEB_ROOT, file);
    if (SELF.has(rel) || /\.test\.(mjs|ts)$/.test(rel)) continue;
    const src = readFileSync(file, "utf8");
    const isClient = /^\s*["']use client["'];?/m.test(src.split("\n").slice(0, 3).join("\n"));
    for (const { names, specifier } of importsOf(src)) {
      if (isClient && resolvesToApiLayer(specifier, rel, "lib/api.server")) {
        problems.push(`${rel}: "use client" 文件不得引入服务端取数模块（import { ${names.join(", ")} } from "${specifier}"）`);
      }
      if (!isClient && resolvesToApiLayer(specifier, rel, "lib/api")) {
        const fetched = names.filter((n) => FETCH_FNS.includes(n));
        if (fetched.length > 0) {
          problems.push(`${rel}: 服务端文件不得用客户端取数函数（${fetched.join(", ")}）——改用 @/lib/api.server`);
        }
      }
    }
  }
}

if (problems.length > 0) {
  console.error("取数层静态检查未通过：");
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log("取数层静态检查通过：客户端与服务端取数层无交叉引用");
