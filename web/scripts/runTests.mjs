import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const suites = JSON.parse(readFileSync(join(root, "test-suites.json"), "utf8"));
const selected = process.argv[2];
if (!(selected in suites)) throw new Error(`Unknown test suite: ${selected}`);
function find(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((item) => {
    const path = join(dir, item.name);
    return item.isDirectory() ? find(path) : item.name.endsWith(".test.mjs") ? [relative(root, path)] : [];
  });
}
const declared = Object.values(suites).flat();
const actual = find(join(root, "lib"));
const missing = actual.filter((name) => !declared.includes(name));
const stale = declared.filter((name) => !actual.includes(name));
if (missing.length || stale.length || new Set(declared).size !== declared.length) {
  throw new Error(`Invalid test inventory: missing=${missing}, stale=${stale}, duplicate=${new Set(declared).size !== declared.length}`);
}
if (!suites[selected].length) throw new Error("Empty test suite");
const command = selected === "unit" ? process.execPath : join(root, "node_modules/.bin/tsx");
const flags = selected === "unit" ? ["--test", "--experimental-strip-types"] : ["--conditions=react-server", "--test"];
const result = spawnSync(command, [...flags, ...suites[selected]], { cwd: root, stdio: "inherit" });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
