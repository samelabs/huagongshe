import type { Metadata } from "next";
import t from "@/lib/i18n";

export const metadata: Metadata = {
  title: { absolute: `${t.mcp.hero}｜${t.brand.name}` },
  description: t.mcp.heroBody,
  alternates: { canonical: "/mcp-guide" },
};

export default function McpGuideLayout({ children }: { children: React.ReactNode }) {
  return children;
}
