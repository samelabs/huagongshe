"use client";

import { useAccount } from "@/components/shared/AccountContext";
import { useWorkbenchCounts } from "./WorkbenchCountsContext";
import { useDictionary } from "@/components/shared/I18nContext";
import { ActivityPanel } from "./panels/ActivityPanel";
import { HomePanel } from "./panels/HomePanel";
import { NotesPanel } from "./panels/NotesPanel";
import { RelationshipsPanel } from "./panels/RelationshipsPanel";
import { ReactionsPanel } from "./panels/ReactionsPanel";
import { SavedPanel } from "./panels/SavedPanel";
import { SearchPanel } from "./panels/SearchPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { StoichPanel } from "./panels/StoichPanel";
import type {
  ChemicalFollow,
  NoticeResponse,
  NoteResponse,
  NoteVisibility,
  PageResponse,
  Reaction,
  ReactionResponse,
  ReactionVisibility,
  SavedKind,
  SkillItem,
  Summary,
  WorkbenchTab,
} from "./types";
import type { PersonSummary } from "@/components/shared/PersonList";

export function WorkbenchLayout({
  activeTab,
  page,
  visibility,
  noteVisibility,
  savedKind,
  summary,
  initialNotes,
  filterChemicalId,
  filterReactionId,
  initialReactions,
  initialChemicals,
  initialSavedReactions,
  initialNotices,
  initialPeople,
  initialSkills,
  searchQuery,
  createNote,
  editNoteId,
  initialChemicalId,
  initialReactionId,
}: {
  activeTab: WorkbenchTab;
  page: number;
  visibility: ReactionVisibility;
  noteVisibility: NoteVisibility;
  savedKind: SavedKind;
  summary: Summary | null;
  initialNotes: NoteResponse | null;
  filterChemicalId?: number;
  filterReactionId?: number;
  initialReactions: ReactionResponse | null;
  initialChemicals: PageResponse<ChemicalFollow> | null;
  initialSavedReactions: PageResponse<Reaction> | null;
  initialNotices: NoticeResponse | null;
  initialPeople: PageResponse<PersonSummary> | null;
  initialSkills: PageResponse<SkillItem> | null;
  searchQuery?: string;
  createNote?: boolean;
  /** Step 7 Part C: /aichem?tab=notes&edit=<id> 直接打开该笔记编辑器 */
  editNoteId?: number;
  initialChemicalId?: number;
  initialReactionId?: number;
}) {
  const { user, ready: authReady } = useAccount();
  const t = useDictionary();
  const { counts } = useWorkbenchCounts();

  if (authReady && !user) return <div className="wb-auth-required"><div><strong>{t.common.loginRequired}</strong><span>{t.common.loginHint}</span></div></div>;

  return (
    <>
      {activeTab === "home" && <HomePanel counts={counts} initialNotes={initialNotes} initialReactions={initialReactions} />}
      {activeTab === "notes" && <NotesPanel
        page={page}
        visibility={noteVisibility}
        initialData={initialNotes}
        createOpen={createNote}
        editNoteId={editNoteId}
        initialChemicalId={initialChemicalId}
        initialReactionId={initialReactionId}
        filterChemicalId={filterChemicalId}
        filterReactionId={filterReactionId}
      />}
      {activeTab === "search" && <SearchPanel initialQuery={searchQuery} />}
      {activeTab === "stoich" && <StoichPanel />}
      {activeTab === "mine" && <ReactionsPanel page={page} visibility={visibility} initialData={initialReactions} />}
      {activeTab === "saved" && <SavedPanel page={page} kind={savedKind} initialChemicals={initialChemicals} initialReactions={initialSavedReactions} />}
      {activeTab === "activity" && <ActivityPanel page={page} initialData={initialNotices} />}
      {activeTab === "skills" && <SkillsPanel page={page} initialData={initialSkills} />}
      {(activeTab === "followers" || activeTab === "following") && <RelationshipsPanel page={page} kind={activeTab} initialData={initialPeople} username={summary?.username} />}
    </>
  );
}
