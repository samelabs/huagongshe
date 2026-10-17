import type { MetadataRoute } from "next";

import { SITEMAP_URL } from "./sitemap";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // /api/ 是后端代理
        disallow: ["/api/"],
      },
    ],
    sitemap: SITEMAP_URL,
  };
}
