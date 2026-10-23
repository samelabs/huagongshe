import type { NextConfig } from "next";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { networkInterfaces } from "node:os";

/**
 * 线上只读截图的 build 标记(纪律）：dev 环境把当前 commit 短哈希
 * 经 env 注入为 HGS_BUILD_SHA，app/layout.tsx 在 <html data-build> 输出，
 * 截图工具（shoot.mjs，位于库外归档 huagongshe-archive/rc-acceptance-tools）
 * 断言「渲染的 UI = 当前 commit」。只在 NODE_ENV=development
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

/**
 * 产品版本单源 = 仓库根 VERSION（与 /api/health 的 app.version、MCP
 * serverInfo.version 同源）。构建时读入注入 NEXT_PUBLIC_APP_VERSION，
 * 页脚展示随发布自动更新；文件缺失/为空直接 build 失败——web 侧不允许
 * 出现第二个版本声明（package.json 不带 version 字段）。
 */
function appVersion(): string {
  const versionFile = join(process.cwd(), "..", "VERSION");
  const value = readFileSync(versionFile, "utf8").trim();
  if (!value) {
    throw new Error(`仓库根 VERSION 文件为空: ${versionFile}`);
  }
  return value;
}

/**
 * 开发服务器放行的本机来源：手机经局域网访问时，Next 默认拦截跨源的开发资源
 * （HMR 与脚本不执行、页面不水合）。回环地址同样要放行——用
 * http://127.0.0.1:3000 打开时 Origin 与默认主机名 localhost 不同源，
 * 不放行则 HMR websocket 被拒、页面不水合（localhost 打开则正常）。
 * 仅 development 生效，生产恒为空名单。
 */
function devLanOrigins(): string[] {
  if (process.env.NODE_ENV !== "development") return [];
  return [
    "127.0.0.1",
    ...Object.values(networkInterfaces())
      .flat()
      .filter((n) => n && n.family === "IPv4" && !n.internal)
      .map((n) => n!.address),
  ];
}


const nextConfig: NextConfig = {
  poweredByHeader: false,
  allowedDevOrigins: devLanOrigins(),
  // 让 proxy 能看到 RSC 请求头与 _rsc 以判定能否缓存
  skipProxyUrlNormalize: true,
  // 让 RSC 响应按 _rsc 区分 URL，可以安全进入共享缓存
  experimental: {
    validateRSCRequestHeaders: true,
    // proxy 管线对经其路由的请求缓冲请求体并设上限(默认 10MB, 超限静默
    // 截断)。技能包上传走 /api/* → Next BFF → FastAPI, 需容纳应用
    // settings.skill_zip_max_bytes(12MiB) + multipart 开销 —— 与 nginx
    // 上传入口(client_max_body_size 14M)同值对齐; 超过此值的请求被
    // 截断后由 BFF 按 413 拒绝(app/api/[...path]/route.ts)。
    proxyClientMaxBodySize: "14mb",
  },
  env: {
    NEXT_PUBLIC_APP_VERSION: appVersion(),
    ...(buildSha ? { HGS_BUILD_SHA: buildSha } : {}),
  },
  // 本地 dev 的 /uploads 静态服务（生产由 nginx 承担）：
  // 上传文件落 local/uploads（与 hgs_local_api 容器同 bind），由
  // local/stack/uploads_server.py 提供；仅 development 生效，生产零配置。
  ...(process.env.NODE_ENV === "development"
    ? {
        async rewrites() {
          // 目的端去 /uploads 前缀：静态服务以 local/uploads 为根直挂
          return [{ source: "/uploads/:path*", destination: "http://127.0.0.1:3010/:path*" }];
        },
      }
    : {}),
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        // nosniff / Referrer-Policy / Permissions-Policy 由 nginx 对全部响应统一下发。
        // CSP 先 report-only —— 盘点后的 inline script 清单：
        // 1. layout.tsx LA.init 统计初始化（dangerouslySetInnerHTML，id 经
        // 语法白名单校验后插值）→ 需要 script-src 'unsafe-inline' 或改造为
        // nonce（收紧前置条件）；外部源 //sdk.51.la。
        // 2. layout.tsx service worker 注册 inline 脚本 → 同上。
        // 3. reaction/chemical 页 JSON-LD（type=application/ld+json，数据块
        // 不执行，CSP 不约束）。
        // 4. AdSense（可选开启）: pagead2.googlesyndication.com 及其加载链。
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
