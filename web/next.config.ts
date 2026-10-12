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
        // F-09（P2）: CSP 先 report-only —— 盘点后的 inline script 清单：
        //   1. layout.tsx LA.init 统计初始化（dangerouslySetInnerHTML，id 经
        //      语法白名单校验后插值）→ 需要 script-src 'unsafe-inline' 或改造为
        //      nonce（收紧前置条件）；外部源 //sdk.51.la。
        //   2. layout.tsx service worker 注册 inline 脚本 → 同上。
        //   3. reaction/chemical 页 JSON-LD（type=application/ld+json，数据块
        //      不执行，CSP 不约束）。
        //   4. AdSense（可选开启）: pagead2.googlesyndication.com 及其加载链。
        // 收紧路径：观察线上 violation（浏览器 console / 未来接 report-uri）→
        // 统计与 SW 脚本改 nonce/移除内联 → 转 enforcing 头。
        {
          key: "Content-Security-Policy-Report-Only",
          value: [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://sdk.51.la https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net https://tpc.googlesyndication.com",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https:",
            "font-src 'self' data:",
            "connect-src 'self' https://sdk.51.la https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net",
            "worker-src 'self'",
            "manifest-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-src https://googleads.g.doubleclick.net https://tpc.googlesyndication.com",
            "frame-ancestors 'none'",
          ].join("; "),
        },
      ],
    }];
  },
};

export default nextConfig;
