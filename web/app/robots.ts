import type { MetadataRoute } from "next";

import { SITEMAP_URL } from "./sitemap";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // /api/ 是后端代理；/dev-ui 是开发预览页（production 下本身 404，
        // 这里按任意 locale 前缀一并排除，如 /zh-CN/dev-ui）
        disallow: ["/api/", "/dev-ui", "/*/dev-ui"],
      },
    ],
    sitemap: SITEMAP_URL,
  };
}
