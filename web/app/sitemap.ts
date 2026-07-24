import type { MetadataRoute } from "next";

const BASE_URL = "https://huagongshe.com";
const API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api";
const PAGE_SIZE = 50000;

type SitemapBatch = { reactions: { id: number; updated_at: string }[]; last_id: number | null };

async function fetchReactionBatch(afterId: number): Promise<SitemapBatch> {
  const response = await fetch(
    `${API_BASE}/sitemap/reactions?after_id=${afterId}&limit=${PAGE_SIZE}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`sitemap API ${response.status}`);
  return response.json() as Promise<SitemapBatch>;
}

export async function generateSitemaps() {
  // First fetch determines how many 50K-page sitemaps we need.
  const first = await fetchReactionBatch(0);
  const count = first.reactions.length;
  if (count === 0) return [{ id: 0 }];
  // If the first batch is exactly PAGE_SIZE, there may be more pages.
  // If it's less, this single sitemap is enough.
  const sitemapCount = count < PAGE_SIZE ? 1 : Math.ceil(count / PAGE_SIZE) + 1;
  return Array.from({ length: sitemapCount }, (_, i) => ({ id: i }));
}

export default async function sitemap(props: { id: Promise<string> }): Promise<MetadataRoute.Sitemap> {
  const id = Number(await props.id);
  const afterId = id * PAGE_SIZE;
  const batch = await fetchReactionBatch(afterId);

  const reactionUrls: MetadataRoute.Sitemap = batch.reactions.map((reaction) => ({
    url: `${BASE_URL}/reaction/${reaction.id}`,
    lastModified: reaction.updated_at,
    changeFrequency: "monthly",
    priority: 0.6,
  }));

  // Include the core static pages only in the first sitemap.
  if (id === 0) {
    reactionUrls.unshift(
      { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1 },
      { url: `${BASE_URL}/guide`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.7 },
    );
  }

  return reactionUrls;
}
