import type { MetadataRoute } from "next";
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: "https://huagongshe.com", changeFrequency: "daily", priority: 1 },
    { url: "https://huagongshe.com/submit", changeFrequency: "monthly", priority: .4 },
  ];
}
