import type { Metadata } from "next";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeAlternates } from "@/lib/alternates";

import { buildShareMetadata } from "@/lib/shareMeta";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const shareMeta = buildShareMetadata({
    title: `${t.mcp.hero}｜${t.brand.name}`,
    description: t.mcp.heroBody,
    path: "/mcp-guide",
    locale,
    siteName: t.brand.name,
    ogImage: {
      url: "/og.png",
      width: 1200,
      height: 630,
      alt: t.brand.ogAlt,
    },
    twitterCard: "summary_large_image",
  });
  return {
    title: { absolute: `${t.mcp.hero}｜${t.brand.name}` },
    description: t.mcp.heroBody,
    alternates: localeAlternates("/mcp-guide", locale),
    ...shareMeta,
  };
}

export default function McpGuideLayout({ children }: { children: React.ReactNode }) {
  return children;
}
