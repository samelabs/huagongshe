/* D002 测试专用 module resolver: 'next/server' → node_modules/next/server.js
   (next 包无 ESM exports map, strip-types resolver 不补 .js)。零 production 改动。 */
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

export function resolve(spec, ctx, next) {
  if (spec === "next/server") {
    // 从 parentURL 向上找 web/ 根(含 node_modules)
    let dir = path.dirname(fileURLToPath(ctx.parentURL));
    for (let i = 0; i < 12; i++) {
      if (path.basename(dir) === "web" && !dir.endsWith("/")) {
        return { url: pathToFileURL(path.join(dir, "node_modules", "next", "server.js")).href, shortCircuit: true };
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return next(spec, ctx);
}
