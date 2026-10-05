import type { Metadata } from "next";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return {
    title: { absolute: `${t.mcp.hero}｜${t.brand.name}` },
    description: t.mcp.heroBody,
    alternates: { canonical: "/mcp-guide" },
  };
}

export default function McpGuideLayout({ children }: { children: React.ReactNode }) {
  return children;
}
