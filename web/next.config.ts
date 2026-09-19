import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // E8/B1: 每一代用自己独立的构建产物目录(blue → .next-blue, green → .next-green),
  // 由部署编排注入 HGS_NEXT_DIST_DIR; 未设置时保持 Next 默认(".next")。
  distDir: process.env.HGS_NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
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
