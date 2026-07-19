import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";

const standalone = ".next/standalone";

function replaceDirectory(source, destination) {
  rmSync(destination, { recursive: true, force: true });
  if (existsSync(source)) cpSync(source, destination, { recursive: true });
}

mkdirSync(`${standalone}/.next`, { recursive: true });
replaceDirectory(".next/static", `${standalone}/.next/static`);
replaceDirectory("public", `${standalone}/public`);
