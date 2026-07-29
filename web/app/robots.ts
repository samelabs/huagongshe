import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: [
      "https://huagongshe.com/sitemap/0.xml",
      "https://huagongshe.com/sitemap/1.xml",
    ],
  };
}
