import type { Metadata } from "next";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeAlternates } from "@/lib/alternates";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    title: { absolute: `${t.mcp.hero}｜${t.brand.name}` },
    description: t.mcp.heroBody,
    alternates: localeAlternates("/mcp-guide", locale),
  };
}

export default function McpGuideLayout({ children }: { children: React.ReactNode }) {
  return children;
}
