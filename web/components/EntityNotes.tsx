"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Byline } from "@/components/ui/Byline";
import { Button } from "@/components/ui/Button";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Tag } from "@/components/ui/Tag";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { apiGet, isApiNotFound, type NoteItem, type NoteResponse } from "@/lib/api";
import { withLocale } from "@/lib/localePath";
import { noteListPresentation } from "@/lib/noteHeadline";

type PrivateContext = { chemical?: number; reaction?: number } | null;

const PAGE_SIZE = 20;

/** 时间线行（公开与私有同一规范）：标题（无标题时正文两行截断作主文本）
 *  + 两行摘要 + 实体徽标；公开行带署名，私有行带可见性 Tag。 */
function NoteRow({ note, minePrivate }: { note: NoteItem; minePrivate?: boolean }) {
  const t = useDictionary();
  const locale = useLocale();
  const pres = noteListPresentation(note);
  const href = withLocale(`/note/${note.slug}`, locale);
  return (
    <article className="entity-note-row">
      <div className="entity-note-row-head">
        {minePrivate
          ? <><Tag>{t.notes.visibilityPrivate}</Tag><time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time></>
          : <Byline user={note} time={new Date(note.updated_at).toLocaleDateString(locale)} />}
      </div>
      {pres.title
        ? <h3 className="entity-note-title"><Link href={href}>{pres.title}</Link></h3>
        : <Link href={href} className="entity-note-title is-body note-clamp-2">{pres.body}</Link>}
      {pres.title && pres.body && <p className="note-clamp-2">{pres.body}</p>}
      {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
        <div className="entity-note-links">
          {note.chemical_ids.slice(0, 3).map((id) => <Link key={`c-${id}`} href={withLocale(`/chemical/${id}`, locale)}><EntityBadge kind="chemical" id={id} size="xs" /></Link>)}
          {note.reaction_ids.slice(0, 3).map((id) => <Link key={`r-${id}`} href={withLocale(`/reaction/${id}`, locale)}><EntityBadge kind="reaction" id={id} size="xs" /></Link>)}
        </div>
      )}
    </article>
  );
}

/** Read-time privacy: private notes are fetched with the viewer session and
 *  merged into the SAME timeline above the public rows (only visible to the
 *  owner); nothing private ever enters the public block data (different
 *  request, different state). */
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
  const [page, setPage] = useState(1);
  const [minePrivate, setMinePrivate] = useState<NoteItem[]>([]);

  // 公开笔记分页（page 变化即重取；在飞请求经 active 标记丢弃）
  useEffect(() => {
    let active = true;
    const path = entity === "chemical"
      ? `/chemicals/${entityId}/notes?page=${page}&page_size=${PAGE_SIZE}`
      : `/reactions/${entityId}/notes?page=${page}&page_size=${PAGE_SIZE}`;
    apiGet<NoteResponse>(path).then((value) => {
      if (active) { setData(value); setError(false); }
    }).catch((err: unknown) => {
      if (!active) return;
      if (isApiNotFound(err)) {
        setData({ items: [], total: 0, page: 1, page_size: PAGE_SIZE });
        setError(false);
      } else setError(true);
    });
    return () => { active = false; };
  }, [entity, entityId, page]);

  // 我的私有笔记（同实体过滤）—— 合入同一条时间线，仅带可见性 Tag
  useEffect(() => {
    if (!privateContext) return;
    let active = true;
    const kind = privateContext.chemical != null ? "chemical" : "reaction";
    const id = privateContext.chemical ?? privateContext.reaction ?? 0;
    apiGet<NoteResponse>(`/users/me/notes?visibility=private&${kind}_id=${id}&page=1&page_size=${PAGE_SIZE}`).then((value) => {
      if (active) setMinePrivate(value.items);
    }).catch(() => { /* 私有读取失败只少一块，不挡公开列表 */ });
    return () => { active = false; };
  }, [privateContext]);

  const createHref = entity === "chemical"
    ? `/aichem?tab=notes&new=1&chemical=${entityId}`
    : `/aichem?tab=notes&new=1&reaction=${entityId}`;
  const title = entity === "chemical" ? t.notes.linkedTitleChemical : t.notes.linkedTitleReaction;
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  return (
    <section className="hg-section entity-notes" id="linked-notes">
      <div className="section-heading entity-notes-heading">
        <h2 className="hg-section-title">{title}</h2>
        {canAdd && <Button variant="tonal" size="sm" href={withLocale(createHref, locale)}>{t.notes.add}</Button>}
      </div>
      {error && <p className="quiet-empty">{t.notes.loadFailed}</p>}
      {!error && data === null && <p className="quiet-empty">{t.common.loading}</p>}
      {!error && data && data.items.length === 0 && minePrivate.length === 0 && <p className="quiet-empty">{t.notes.emptyPublic}</p>}
      {!error && data && (data.items.length > 0 || minePrivate.length > 0) && (
        <>
          <div className="entity-note-list">
            {minePrivate.map((note) => <NoteRow key={`mine-${note.id}`} note={note} minePrivate />)}
            {data.items.map((note) => <NoteRow key={note.id} note={note} />)}
          </div>
          {data.total > data.page_size && (
            <nav className="pf-pagination" aria-label={t.common.pageNav}>
              <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage((value) => Math.max(value - 1, 1))}>{t.common.prev}</Button>
              <small className="pf-pagination-page">{t.common.pageOf(page, totalPages)}</small>
              <Button variant="ghost" size="sm" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>{t.common.next}</Button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
