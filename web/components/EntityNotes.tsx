"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { apiGet, isApiNotFound, type NoteResponse } from "@/lib/api";
import { withLocale } from "@/lib/localePath";

export function EntityNotes({ entity, entityId, canAdd }: {
  entity: "chemical" | "reaction";
  entityId: number;
  canAdd: boolean;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const [data, setData] = useState<NoteResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    const path = entity === "chemical"
      ? `/chemicals/${entityId}/notes?page=1&page_size=20`
      : `/reactions/${entityId}/notes?page=1&page_size=20`;
    apiGet<NoteResponse>(path).then((value) => {
      if (active) { setData(value); setError(false); }
    }).catch((err: unknown) => {
      if (!active) return;
      if (isApiNotFound(err)) {
        setData({ items: [], total: 0, page: 1, page_size: 20 });
        setError(false);
      } else setError(true);
    });
    return () => { active = false; };
  }, [entity, entityId]);

  const createHref = entity === "chemical"
    ? `/aichem?tab=notes&new=1&chemical=${entityId}`
    : `/aichem?tab=notes&new=1&reaction=${entityId}`;

  return (
    <section className="chem-section entity-notes" id="linked-notes">
      <div className="section-heading entity-notes-heading">
        <div><p>NOTES</p><h2>{t.notes.linkedTitle}</h2></div>
        {canAdd && <Link className="text-button" href={withLocale(createHref, locale)}>{t.notes.add}</Link>}
      </div>
      {error && <p className="quiet-empty">{t.notes.loadFailed}</p>}
      {!error && data === null && <p className="quiet-empty">{t.common.loading}</p>}
      {!error && data && data.items.length === 0 && <p className="quiet-empty">{t.notes.emptyPublic}</p>}
      {!error && data && data.items.length > 0 && (
        <div className="entity-note-list">
          {data.items.map((note) => (
            <article className="entity-note-card" key={note.id}>
              <header>
                <Link href={withLocale(`/user/${note.username}`, locale)}>{note.display_name || `@${note.username}`}</Link>
                <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time>
              </header>
              <p>{note.content}</p>
              {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
                <div className="entity-note-links">
                  {note.chemical_ids.map((id) => <Link key={`c-${id}`} href={withLocale(`/chemical/${id}`, locale)}><EntityId kind="chemical" id={id} compact /></Link>)}
                  {note.reaction_ids.map((id) => <Link key={`r-${id}`} href={withLocale(`/reaction/${id}`, locale)}><EntityId kind="reaction" id={id} compact /></Link>)}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
