import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { UserDashboard, type DashboardTab, type ReactionVisibility, type SavedKind } from "@/components/UserDashboard";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.me.title, robots: { index: false, follow: false } };
const tabs = new Set<DashboardTab>(["mine", "saved", "activity", "followers", "following"]);
const visibilities = new Set<ReactionVisibility>(["all", "public", "private"]);
const savedKinds = new Set<SavedKind>(["chemicals", "reactions"]);

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function MePage({ searchParams }: { searchParams: Promise<{ tab?: string | string[]; visibility?: string | string[]; kind?: string | string[]; page?: string | string[] }> }) {
  const h = await headers();
  const user = await getUser(h.get("cookie"));
  if (!user) redirect("/login?next=/me");

  const query = await searchParams;
  const requested = query.tab;
  const activeTab = typeof requested === "string" && tabs.has(requested as DashboardTab)
    ? requested as DashboardTab
    : requested === "chemicals" || requested === "reactions" ? "saved" : "mine";
  const requestedVisibility = query.visibility;
  const visibility = typeof requestedVisibility === "string" && visibilities.has(requestedVisibility as ReactionVisibility)
    ? requestedVisibility as ReactionVisibility
    : requested === "public" || requested === "private" ? requested : "all";
  const requestedKind = query.kind;
  const savedKind = typeof requestedKind === "string" && savedKinds.has(requestedKind as SavedKind)
    ? requestedKind as SavedKind
    : requested === "reactions" ? "reactions" : "chemicals";
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  return <div className="content-page dashboard-page"><UserDashboard activeTab={activeTab} page={page} visibility={visibility} savedKind={savedKind} /></div>;
}
