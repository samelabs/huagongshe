import type { Metadata } from "next";
import { headers } from "next/headers";
import { WorkbenchLayout } from "@/components/workbench/WorkbenchLayout";
import type {
  ChemicalFollow,
  NoticeResponse,
  NoteResponse,
  NoteVisibility,
  PageResponse,
  ReactionResponse,
  ReactionVisibility,
  Reaction,
  SavedKind,
  SkillItem,
  Summary,
  WorkbenchTab,
} from "@/components/workbench/types";
import type { PersonSummary } from "@/components/shared/PersonList";
import { apiGet } from "@/lib/api";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.me.title, robots: { index: false, follow: false } };
}
const tabs = new Set<WorkbenchTab>(["home", "notes", "search", "stoich", "mine", "saved", "skills", "activity", "followers", "following"]);
const visibilities = new Set<ReactionVisibility>(["all", "public", "private"]);
const noteVisibilities = new Set<NoteVisibility>(["all", "public", "private"]);
const savedKinds = new Set<SavedKind>(["chemicals", "reactions"]);

/**
 * F1: SSR notes prefetch query. Chemical takes precedence when both
 * chemical= and reaction= are present — mirroring the client-side
 * apiListQuery exactly so first paint and client refresh agree.
 */
function ssrNotesQuery(visibility: string, chemicalId: number | undefined, reactionId: number | undefined, page: number): string {
  const params = new URLSearchParams();
  params.set("visibility", visibility);
  if (chemicalId != null) params.set("chemical_id", String(chemicalId));
  else if (reactionId != null) params.set("reaction_id", String(reactionId));
  params.set("page", String(page));
  params.set("page_size", "20");
  return params.toString();
}

async function ssrGet<T>(cookieHeader: string | null, path: string): Promise<T | null> {
  if (!cookieHeader) return null;
  try {
    return await apiGet<T>(path, { cookie: cookieHeader });
  } catch {
    return null;
  }
}

export default async function AichemPage({ searchParams }: { searchParams: Promise<{
  tab?: string | string[];
  visibility?: string | string[];
  kind?: string | string[];
  page?: string | string[];
  q?: string | string[];
  new?: string | string[];
  chemical?: string | string[];
  reaction?: string | string[];
  edit?: string | string[];
}> }) {
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
  const noteVisibility = typeof requestedVisibility === "string" && noteVisibilities.has(requestedVisibility as NoteVisibility)
    ? requestedVisibility as NoteVisibility
    : "all";
  const requestedKind = query.kind;
  const savedKind = typeof requestedKind === "string" && savedKinds.has(requestedKind as SavedKind)
    ? requestedKind as SavedKind
    : "chemicals";
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const searchQuery = typeof query.q === "string" ? query.q : undefined;
  const createNote = activeTab === "notes" && query.new === "1";
  // Step 7 Part C: ?edit=<id> 直接打开该笔记的编辑器（笔记详情页「编辑」入口）
  const editNoteId = activeTab === "notes" && typeof query.edit === "string" && /^\d+$/.test(query.edit)
    ? Number(query.edit) : undefined;
  const initialChemicalId = typeof query.chemical === "string" && /^\d+$/.test(query.chemical)
    ? Number(query.chemical) : undefined;
  const initialReactionId = typeof query.reaction === "string" && /^\d+$/.test(query.reaction)
    ? Number(query.reaction) : undefined;
  // P-8: notes-tab entity filter (chemical precedence). Distinct from the
  // create-preset params: new=1 + chemical/reaction stays a pre-association;
  // without new=1 the same param filters the list.
  const filterChemicalId = activeTab === "notes" && !createNote ? initialChemicalId : undefined;
  const filterReactionId = activeTab === "notes" && !createNote ? initialReactionId : undefined;

  // 1. 先拿 summary（followers/following 依赖 username）
  const summary = await ssrGet<Summary>(cookieHeader, "/users/me/dashboard");

  // 2. 当前 tab 数据并行预取（只发一个请求，不浪费）
  const initialNotes = (activeTab === "notes" || activeTab === "home")
    ? ssrGet<NoteResponse>(
        cookieHeader,
        activeTab === "home"
          ? "/users/me/notes?visibility=all&page=1&page_size=4"
          : `/users/me/notes?${ssrNotesQuery(noteVisibility, filterChemicalId, filterReactionId, page)}`,
      )
    : null;
  const initialReactions = activeTab === "home"
    ? ssrGet<ReactionResponse>(cookieHeader, "/users/me/reactions?visibility=all&page=1&page_size=4")
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
  const initialSkills = activeTab === "skills"
    ? ssrGet<PageResponse<SkillItem>>(cookieHeader, `/skills?scope=mine&page=${page}&page_size=20`)
    : null;

  // 等待并行请求完成
  const [notes, reactions, chemicals, savedReactions, notices, people, skills] = await Promise.all([
    initialNotes,
    initialReactions,
    initialChemicals,
    initialSavedReactions,
    initialNotices,
    initialPeople,
    initialSkills,
  ]);

  return (
    <WorkbenchLayout
      activeTab={activeTab}
      page={page}
      visibility={visibility}
      noteVisibility={noteVisibility}
      savedKind={savedKind}
      summary={summary}
      initialNotes={notes}
      initialReactions={reactions}
      initialChemicals={chemicals}
      initialSavedReactions={savedReactions}
      initialNotices={notices}
      initialPeople={people}
      initialSkills={skills}
      searchQuery={searchQuery}
      createNote={createNote}
      editNoteId={editNoteId}
      initialChemicalId={initialChemicalId}
      initialReactionId={initialReactionId}
      filterChemicalId={filterChemicalId}
      filterReactionId={filterReactionId}
    />
  );
}
