"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { EntityId } from "@/components/shared/EntityId";
import { apiDelete, apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { NoteEditor } from "../NoteEditor";
import { PanelError, PanelHeading, PanelLoading, Pagination, WbEmpty } from "../shared";
import type { LoadState, NoteItem, NoteResponse, NoteVisibility, PanelProps } from "../types";

const empty = (): NoteResponse => ({ items: [], total: 0, page: 1, page_size: 20 });

/** Entity filter param serialization — single source of truth for both the
 * page URL params (chemical/reaction) and the API query params
 * (chemical_id/reaction_id). Chemical wins when both are present (P-8). */
function filterParams(chemicalId?: number, reactionId?: number): URLSearchParams {
  const params = new URLSearchParams();
  if (chemicalId != null) params.set("chemical", String(chemicalId));
  else if (reactionId != null) params.set("reaction", String(reactionId));
  return params;
}

/** Full list-page URL params for a given view state. */
function listParams(visibility: NoteVisibility, chemicalId?: number, reactionId?: number, page = 1): URLSearchParams {
  const params = filterParams(chemicalId, reactionId);
  if (visibility !== "all") params.set("visibility", visibility);
  if (page > 1) params.set("page", String(page));
  return params;
}

/** API query string: URL filter names map 1:1 to chemical_id/reaction_id. */
function apiListQuery(visibility: NoteVisibility, chemicalId?: number, reactionId?: number, page = 1): string {
  const params = new URLSearchParams();
  params.set("visibility", visibility);
  const filter = filterParams(chemicalId, reactionId);
  if (filter.has("chemical")) params.set("chemical_id", filter.get("chemical")!);
  else if (filter.has("reaction")) params.set("reaction_id", filter.get("reaction")!);
  params.set("page", String(page));
  params.set("page_size", "20");
  return params.toString();
}

export function NotesPanel({
  page,
  visibility,
  initialData,
  createOpen = false,
  initialChemicalId,
  initialReactionId,
  filterChemicalId,
  filterReactionId,
}: PanelProps & {
  visibility: NoteVisibility;
  initialData?: NoteResponse | null;
  createOpen?: boolean;
  initialChemicalId?: number;
  initialReactionId?: number;
  filterChemicalId?: number;
  filterReactionId?: number;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const [data, setData] = useState<NoteResponse>(initialData ?? empty());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState<NoteItem | null>(null);
  const [creating, setCreating] = useState(createOpen);
  const [createContext, setCreateContext] = useState(() => ({
    chemicalIds: initialChemicalId ? [initialChemicalId] : [] as number[],
    reactionIds: initialReactionId ? [initialReactionId] : [] as number[],
  }));
  const mounted = useRef(false);
  const latestLoad = useRef(0);

  // One filter identity: chemical takes precedence over reaction (P-8).
  const filterKey = filterChemicalId != null ? "chemical" : filterReactionId != null ? "reaction" : null;
  const filterId = filterChemicalId ?? filterReactionId;

  function listHref(targetPage: number): string {
    return withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(visibility, filterChemicalId, filterReactionId, targetPage)) }).toString()}`, locale);
  }

  function redirectIfPageIsEmpty(value: NoteResponse): boolean {
    if (page <= 1 || value.items.length > 0) return false;
    const lastPage = Math.max(1, Math.ceil(value.total / value.page_size));
    router.replace(listHref(lastPage));
    return true;
  }

  async function load() {
    const requestId = ++latestLoad.current;
    setState("loading");
    setError(null);
    try {
      const value = await apiGet<NoteResponse>(`/users/me/notes?${apiListQuery(visibility, filterChemicalId, filterReactionId, page)}`);
      if (requestId !== latestLoad.current) return;
      if (redirectIfPageIsEmpty(value)) return;
      setData(value);
      setState("ready");
    } catch (err) {
      if (requestId !== latestLoad.current) return;
      setError(err);
      setState("error");
    }
  }

  useEffect(() => {
    if (!mounted.current && initialData) {
      mounted.current = true;
      if (redirectIfPageIsEmpty(initialData)) return;
      return;
    }
    mounted.current = true;
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibility, page, filterKey, filterId]);

  useEffect(() => {
    if (createOpen) {
      setEditing(null);
      setCreateContext({
        chemicalIds: initialChemicalId ? [initialChemicalId] : [],
        reactionIds: initialReactionId ? [initialReactionId] : [],
      });
      setCreating(true);
    }
  }, [createOpen, initialChemicalId, initialReactionId]);

  function closeEditor() {
    setCreating(false);
    setEditing(null);
    if (createOpen) router.replace(listHref(1));
  }

  /** R3: never strand the user on a list where the note they just saved
   * cannot appear. page=1 + the list can show it → refresh in place;
   * otherwise navigate to page 1 of the filter with the saved note's
   * own visibility (a private note saved under a public filter etc.). */
  async function handleSaved(saved: NoteItem) {
    const created = creating && !editing;
    setCreating(false);
    setEditing(null);
    if (created) setCreateContext({ chemicalIds: [], reactionIds: [] });

    const visibleHere = visibility === "all" || visibility === saved.visibility;
    const inFilter = filterKey === null
      || (filterKey === "chemical" && saved.chemical_ids.includes(filterChemicalId!))
      || (filterKey === "reaction" && saved.reaction_ids.includes(filterReactionId!));

    if (page === 1 && visibleHere && inFilter) {
      await load();
      if (createOpen) router.replace(listHref(1));
      return;
    }
    // F2: the landing list must actually contain the saved note. When the
    // note no longer matches the current entity filter, DROP the filter
    // instead of keeping it — keeping it would navigate to a list the note
    // cannot appear in. Keep it only when the note still references the
    // filtered entity (e.g. an edit that removed other references).
    const params = new URLSearchParams({ tab: "notes" });
    params.set("visibility", saved.visibility);
    if (filterKey === "chemical" && saved.chemical_ids.includes(filterChemicalId!)) {
      params.set("chemical", String(filterChemicalId));
    } else if (filterKey === "reaction" && saved.reaction_ids.includes(filterReactionId!)) {
      params.set("reaction", String(filterReactionId));
    }
    router.replace(withLocale(`/aichem?${params.toString()}`, locale));
  }

  async function remove(note: NoteItem) {
    if (!window.confirm(t.me.notesDeleteConfirm)) return;
    setActionError(null);
    try {
      await apiDelete(`/notes/${note.id}`);
      if (editing?.id === note.id) setEditing(null);
      await load();
    } catch (err) {
      // R6: keep the loaded list interactive — surface the failure without
      // switching the whole panel to a fatal error state.
      setActionError(t.notes.deleteFailed);
      setError(err);
    }
  }

  const labels: Record<NoteVisibility, string> = {
    all: t.me.filterAll,
    private: t.common.private,
    public: t.common.public,
  };

  return (
    <section className="wb-panel wb-notes">
      <PanelHeading
        title={t.nav.tabNotes}
        subtitle={t.me.notesHint}
        count={state === "ready" ? data.total : "—"}
        unit={t.me.unitNote}
        action={
          <button className="wb-btn wb-btn-primary" type="button" onClick={() => {
            setEditing(null);
            setCreateContext({ chemicalIds: [], reactionIds: [] });
            setCreating(true);
          }}>
            {t.me.notesNew}
          </button>
        }
      />

      <nav className="wb-filters" aria-label={t.me.notesFilter}>
        {(["all", "private", "public"] as NoteVisibility[]).map((value) => (
          <Link
            key={value}
            className={visibility === value ? "active" : ""}
            href={withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(value, filterChemicalId, filterReactionId)) }).toString()}`, locale)}
          >
            {labels[value]}
          </Link>
        ))}
      </nav>

      {/* P-8: entity filter breadcrumb — chemical takes precedence when both
          params exist; clear returns to the unfiltered list. */}
      {filterKey && (
        <div className="wb-filter-crumbs">
          <span className="wb-filter-crumb">
            {filterKey === "chemical" ? t.notes.filterChemical : t.notes.filterReaction}: <EntityId kind={filterKey} id={filterId!} compact />
          </span>
          <Link className="text-button" href={withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(visibility)) }).toString()}`, locale)}>
            {t.notes.filterClear}
          </Link>
        </div>
      )}

      {(creating || editing) && (
        <NoteEditor
          key={editing
            ? `edit-${editing.id}`
            : `new-${createContext.chemicalIds.join("-") || 0}-${createContext.reactionIds.join("-") || 0}`}
          note={editing}
          initialChemicalIds={!editing ? createContext.chemicalIds : []}
          initialReactionIds={!editing ? createContext.reactionIds : []}
          onCancel={closeEditor}
          onSaved={handleSaved}
        />
      )}

      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {/* R6: delete failure keeps the list mounted with a recoverable state */}
      {actionError && state !== "error" && (
        <p className="wb-panel-inline-error" role="alert">{actionError}</p>
      )}
      {state === "ready" && (data.items.length ? (
        <div className="wb-note-list">
          {data.items.map((note) => (
            <article key={note.id} className="wb-note-card">
              <header>
                <span>{note.visibility === "private" ? t.common.private : t.common.public}</span>
                <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleString(locale)}</time>
              </header>
              <p className="note-clamp">{note.content}</p>
              {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
                <div className="wb-note-links">
                  {note.chemical_ids.map((id) => (
                    <Link key={`c-${id}`} href={withLocale(`/chemical/${id}`, locale)}>
                      <EntityId kind="chemical" id={id} compact />
                    </Link>
                  ))}
                  {note.reaction_ids.map((id) => (
                    <Link key={`r-${id}`} href={withLocale(`/reaction/${id}`, locale)}>
                      <EntityId kind="reaction" id={id} compact />
                    </Link>
                  ))}
                </div>
              )}
              <footer>
                <Link className="text-button" href={withLocale(`/note/${note.id}`, locale)}>{t.notes.viewFull}</Link>
                <button type="button" onClick={() => { setCreating(false); setEditing(note); }}>{t.common.edit}</button>
                <button type="button" onClick={() => void remove(note)}>{t.common.delete}</button>
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <WbEmpty text={filterKey ? t.notes.filterEmpty : t.me.notesEmpty} />
      ))}

      {state === "ready" && data.total > data.page_size && (
        <Pagination
          page={page}
          pageSize={data.page_size}
          total={data.total}
          href={(value) => listHref(value)}
        />
      )}
    </section>
  );
}
