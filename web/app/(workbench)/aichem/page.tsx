import type { Metadata } from "next";
import { headers } from "next/headers";
import { WorkbenchLayout } from "@/components/workbench/WorkbenchLayout";
import type {
  ChemicalFollow,
  NoticeResponse,
  PageResponse,
  ReactionResponse,
  ReactionVisibility,
  Reaction,
  SavedKind,
  Summary,
  WorkbenchTab,
} from "@/components/workbench/types";
import type { PersonSummary } from "@/components/shared/PersonList";
import { apiGet } from "@/lib/api";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.me.title, robots: { index: false, follow: false } };
const tabs = new Set<WorkbenchTab>(["home", "search", "stoich", "mine", "saved", "activity", "followers", "following"]);
const visibilities = new Set<ReactionVisibility>(["all", "public", "private"]);
const savedKinds = new Set<SavedKind>(["chemicals", "reactions"]);

async function ssrGet<T>(cookieHeader: string | null, path: string): Promise<T | null> {
  if (!cookieHeader) return null;
  try {
    return await apiGet<T>(path, { cookie: cookieHeader });
  } catch {
    return null;
  }
}

export default async function AichemPage({ searchParams }: { searchParams: Promise<{ tab?: string | string[]; visibility?: string | string[]; kind?: string | string[]; page?: string | string[]; q?: string | string[] }> }) {
  const h = await headers();
  const cookieHeader = h.get("cookie");

  const query = await searchParams;
  const requested = query.tab;
  const activeTab = typeof requested === "string" && tabs.has(requested as WorkbenchTab)
    ? requested as WorkbenchTab
    : "home";
  const requestedVisibility = query.visibility;
  const visibility = typeof requestedVisibility === "string" && visibilities.has(requestedVisibility as ReactionVisibility)
    ? requestedVisibility as ReactionVisibility
    : "all";
  const requestedKind = query.kind;
  const savedKind = typeof requestedKind === "string" && savedKinds.has(requestedKind as SavedKind)
    ? requestedKind as SavedKind
    : "chemicals";
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const searchQuery = typeof query.q === "string" ? query.q : undefined;

  // 1. 先拿 summary（followers/following 依赖 username）
  const summary = await ssrGet<Summary>(cookieHeader, "/users/me/dashboard");

  // 2. 当前 tab 数据并行预取（只发一个请求，不浪费）
  const initialReactions = activeTab === "home"
    ? ssrGet<ReactionResponse>(cookieHeader, "/users/me/reactions?visibility=public&page=1&page_size=4")
    : activeTab === "mine"
      ? ssrGet<ReactionResponse>(cookieHeader, `/users/me/reactions?visibility=${visibility}&page=${page}&page_size=20`)
      : null;
  const initialChemicals = activeTab === "saved" && savedKind === "chemicals"
    ? ssrGet<PageResponse<ChemicalFollow>>(cookieHeader, `/users/me/follows/chemicals?page=${page}&page_size=40`)
    : null;
  const initialSavedReactions = activeTab === "saved" && savedKind === "reactions"
    ? ssrGet<PageResponse<Reaction>>(cookieHeader, `/users/me/follows/reactions?page=${page}&page_size=20`)
    : null;
  const initialNotices = activeTab === "activity"
    ? ssrGet<NoticeResponse>(cookieHeader, `/users/me/notifications?page=${page}&page_size=50`)
    : null;
  const initialPeople = (activeTab === "followers" || activeTab === "following") && summary?.username
    ? ssrGet<PageResponse<PersonSummary>>(cookieHeader, `/users/${encodeURIComponent(summary.username)}/${activeTab}?page=${page}&page_size=40`)
    : null;

  // 等待并行请求完成
  const [reactions, chemicals, savedReactions, notices, people] = await Promise.all([
    initialReactions,
    initialChemicals,
    initialSavedReactions,
    initialNotices,
    initialPeople,
  ]);

  return (
    <WorkbenchLayout
      activeTab={activeTab}
      page={page}
      visibility={visibility}
      savedKind={savedKind}
      summary={summary}
      initialReactions={reactions}
      initialChemicals={chemicals}
      initialSavedReactions={savedReactions}
      initialNotices={notices}
      initialPeople={people}
      searchQuery={searchQuery}
    />
  );
}
