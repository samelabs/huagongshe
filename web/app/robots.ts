import type { MetadataRoute } from "next";

import { SITEMAP_URL } from "./sitemap";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: SITEMAP_URL,
  };
}
