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

/** Entity filter param serialization: chemical wins when both are present. */
function filterQuery(chemicalId?: number, reactionId?: number): string {
  if (chemicalId != null) return `&chemical=${chemicalId}`;
  if (reactionId != null) return `&reaction=${reactionId}`;
  return "";
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

  function listHref(targetPage: number) {
    return withLocale(
      `/aichem?tab=notes${visibility === "all" ? "" : `&visibility=${visibility}`}${filterQuery(filterChemicalId, filterReactionId)}${targetPage > 1 ? `&page=${targetPage}` : ""}`,
      locale,
    );
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
      const value = await apiGet<NoteResponse>(`/users/me/notes?visibility=${visibility}${filterQuery(filterChemicalId, filterReactionId).replace("&", "&")}&page=${page}&page_size=20`);
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
    if (createOpen) router.replace(withLocale(`/aichem?tab=notes${filterQuery(filterChemicalId, filterReactionId)}`, locale));
  }

  async function handleSaved() {
    const created = creating && !editing;
    setCreating(false);
    setEditing(null);

    if (created) {
      setCreateContext({ chemicalIds: [], reactionIds: [] });
      // 新建后必须让用户看见刚保存的记录。page=1 + 无筛选可原地刷新；
      // 其他筛选/页码回到当前筛选列表首页，避免保存成功后落在看不到新记录的列表。
      if (page === 1 && filterKey === null) {
        await load();
        if (createOpen) router.replace(withLocale(`/aichem?tab=notes${filterQuery(filterChemicalId, filterReactionId)}`, locale));
      } else {
        router.replace(withLocale(`/aichem?tab=notes${filterQuery(filterChemicalId, filterReactionId)}`, locale));
      }
      return;
    }

    // 编辑保存后刷新当前列表；若 URL 仍带 new=1（例如从新建态切到编辑），
    // 同时归一回 Notes 列表，避免 URL 与实际编辑器状态分叉。
    await load();
    if (createOpen) router.replace(withLocale(`/aichem?tab=notes${filterQuery(filterChemicalId, filterReactionId)}`, locale));
  }

  async function remove(note: NoteItem) {
    if (!window.confirm(t.me.notesDeleteConfirm)) return;
    try {
      await apiDelete(`/notes/${note.id}`);
      if (editing?.id === note.id) setEditing(null);
      await load();
    } catch (err) {
      setError(err);
      setState("error");
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
            href={withLocale(`/aichem?tab=notes${value === "all" ? "" : `&visibility=${value}`}${filterQuery(filterChemicalId, filterReactionId)}`, locale)}
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
          <Link className="text-button" href={withLocale(`/aichem?tab=notes${visibility === "all" ? "" : `&visibility=${visibility}`}`, locale)}>
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
          href={(value) => withLocale(
            `/aichem?tab=notes${visibility === "all" ? "" : `&visibility=${visibility}`}${filterQuery(filterChemicalId, filterReactionId)}${value > 1 ? `&page=${value}` : ""}`,
            locale,
          )}
        />
      )}
    </section>
  );
}
