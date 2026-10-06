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

export function NotesPanel({
  page,
  visibility,
  initialData,
  createOpen = false,
  initialChemicalId,
  initialReactionId,
}: PanelProps & {
  visibility: NoteVisibility;
  initialData?: NoteResponse | null;
  createOpen?: boolean;
  initialChemicalId?: number;
  initialReactionId?: number;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const [data, setData] = useState<NoteResponse>(initialData ?? empty());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<NoteItem | null>(null);
  const [creating, setCreating] = useState(createOpen);
  const mounted = useRef(false);

  async function load() {
    setState("loading");
    setError(null);
    try {
      const value = await apiGet<NoteResponse>(`/users/me/notes?visibility=${visibility}&page=${page}&page_size=20`);
      setData(value);
      setState("ready");
    } catch (err) {
      setError(err);
      setState("error");
    }
  }

  useEffect(() => {
    if (!mounted.current && initialData) {
      mounted.current = true;
      return;
    }
    mounted.current = true;
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibility, page]);

  useEffect(() => {
    if (createOpen) {
      setEditing(null);
      setCreating(true);
    }
  }, [createOpen, initialChemicalId, initialReactionId]);

  function closeEditor() {
    setCreating(false);
    setEditing(null);
    if (createOpen) router.replace(withLocale("/aichem?tab=notes", locale));
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
          <button className="wb-btn wb-btn-primary" type="button" onClick={() => { setEditing(null); setCreating(true); }}>
            {t.me.notesNew}
          </button>
        }
      />

      <nav className="wb-filters" aria-label={t.me.notesFilter}>
        {(["all", "private", "public"] as NoteVisibility[]).map((value) => (
          <Link
            key={value}
            className={visibility === value ? "active" : ""}
            href={withLocale(`/aichem?tab=notes${value === "all" ? "" : `&visibility=${value}`}`, locale)}
          >
            {labels[value]}
          </Link>
        ))}
      </nav>

      {(creating || editing) && (
        <NoteEditor
          key={editing
            ? `edit-${editing.id}`
            : `new-${initialChemicalId ?? 0}-${initialReactionId ?? 0}-${createOpen ? 1 : 0}`}
          note={editing}
          initialChemicalIds={!editing && initialChemicalId ? [initialChemicalId] : []}
          initialReactionIds={!editing && initialReactionId ? [initialReactionId] : []}
          onCancel={closeEditor}
          onSaved={async () => {
            closeEditor();
            await load();
          }}
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
              <p>{note.content}</p>
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
                <button type="button" onClick={() => { setCreating(false); setEditing(note); }}>{t.common.edit}</button>
                <button type="button" onClick={() => void remove(note)}>{t.common.delete}</button>
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <WbEmpty text={t.me.notesEmpty} />
      ))}

      {state === "ready" && data.total > data.page_size && (
        <Pagination
          page={page}
          pageSize={data.page_size}
          total={data.total}
          href={(value) => withLocale(
            `/aichem?tab=notes${visibility === "all" ? "" : `&visibility=${visibility}`}${value > 1 ? `&page=${value}` : ""}`,
            locale,
          )}
        />
      )}
    </section>
  );
}
