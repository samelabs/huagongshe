"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { apiGet, isApiNotFound, type NoteResponse } from "@/lib/api";
import { withLocale } from "@/lib/localePath";

type PrivateContext = { chemical?: number; reaction?: number } | null;

/** Read-time privacy: private notes are fetched with the viewer session and
 * rendered in a separate block above the public block; nothing private ever
 * enters the public block data (different request, different state). */
function MyPrivateNotes({ context }: { context: PrivateContext }) {
  const t = useDictionary();
  const locale = useLocale();
  const [data, setData] = useState<NoteResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const kind = context?.chemical != null ? "chemical" : "reaction";
  const id = context?.chemical ?? context?.reaction ?? 0;

  useEffect(() => {
    let active = true;
    const path = `/users/me/notes?visibility=private&${kind}_id=${id}&page=1&page_size=20`;
    apiGet<NoteResponse>(path).then((value) => {
      if (active) { setData(value); setFailed(false); }
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [kind, id]);

  if (failed || !data || data.items.length === 0) return null;
  const manageHref = `/aichem?tab=notes&${kind}=${id}`;
  return (
    <div className="entity-note-private">
      <div className="entity-note-private-head">
        <h3>{t.notes.mineSection}</h3>
        <Link className="text-button" href={withLocale(manageHref, locale)}>{t.notes.mineManage}</Link>
      </div>
      <div className="entity-note-list">
        {data.items.map((note) => (
          <article className="entity-note-card" key={note.id}>
            <header>
              <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time>
              <Link href={withLocale(`/note/${note.id}`, locale)}>{t.notes.viewFull}</Link>
            </header>
            <p className="note-clamp">{note.content}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

export function EntityNotes({ entity, entityId, canAdd, privateContext }: {
  entity: "chemical" | "reaction";
  entityId: number;
  canAdd: boolean;
  privateContext?: PrivateContext;
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
      {privateContext && <MyPrivateNotes context={privateContext} />}
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
              <p className="note-clamp">{note.content}</p>
              {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
                <div className="entity-note-links">
                  {note.chemical_ids.map((id) => <Link key={`c-${id}`} href={withLocale(`/chemical/${id}`, locale)}><EntityId kind="chemical" id={id} compact /></Link>)}
                  {note.reaction_ids.map((id) => <Link key={`r-${id}`} href={withLocale(`/reaction/${id}`, locale)}><EntityId kind="reaction" id={id} compact /></Link>)}
                </div>
              )}
              <Link className="text-button note-view-full" href={withLocale(`/note/${note.id}`, locale)}>{t.notes.viewFull}</Link>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
