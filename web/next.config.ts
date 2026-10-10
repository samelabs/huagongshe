import type { NextConfig } from "next";
import { execSync } from "node:child_process";

/**
 * 线上只读截图的 build 标记（Step 8 纪律）：dev 环境把当前 commit 短哈希
 * 经 env 注入为 HGS_BUILD_SHA，app/layout.tsx 在 <html data-build> 输出，
 * shoot.mjs 断言「渲染的 UI = 当前 commit」。只在 NODE_ENV=development
 * 注入；生产构建不带 build 指纹（避免按 sha 产生缓存分片）。
 */
function devBuildSha(): string {
  if (process.env.NODE_ENV !== "development") return "";
  try {
    return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] })
      .toString().trim().slice(0, 12);
  } catch {
    return "";
  }
}

const buildSha = devBuildSha();

const nextConfig: NextConfig = {
  poweredByHeader: false,
  ...(buildSha ? { env: { HGS_BUILD_SHA: buildSha } } : {}),
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};

export default nextConfig;
