import type { Metadata } from "next";
import { UserDashboard, type DashboardTab } from "@/components/UserDashboard";

export const metadata: Metadata = { title: "我的反应仓库", robots: { index: false, follow: false } };
const tabs = new Set<DashboardTab>(["public", "private", "people", "followers", "chemicals", "reactions", "activity"]);

export default async function MePage({ searchParams }: { searchParams: Promise<{ tab?: string | string[]; page?: string | string[] }> }) {
  const query = await searchParams;
  const requested = query.tab;
  const activeTab = typeof requested === "string" && tabs.has(requested as DashboardTab) ? requested as DashboardTab : "public";
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  return <div className="content-page dashboard-page"><UserDashboard activeTab={activeTab} page={page} /></div>;
}
