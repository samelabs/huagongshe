"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { EntityId } from "@/components/shared/EntityId";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Segmented } from "@/components/ui/Segmented";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { IconNote } from "@/components/ui/icons";
import { apiDelete, apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { NoteEditor } from "../NoteEditor";
import { PanelError, PanelHeading, PanelLoading, Pagination, VisibilityTag, WbListRow, noteHeadline, relativeTime } from "../shared";
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
  editNoteId,
  initialChemicalId,
  initialReactionId,
  filterChemicalId,
  filterReactionId,
}: PanelProps & {
  visibility: NoteVisibility;
  initialData?: NoteResponse | null;
  createOpen?: boolean;
  /** Step 7 Part C: /aichem?tab=notes&edit=<id> 直接打开该笔记编辑器 */
  editNoteId?: number;
  initialChemicalId?: number;
  initialReactionId?: number;
  filterChemicalId?: number;
  filterReactionId?: number;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const confirm = useConfirm();
  const toast = useToast();
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

  // Step 7 Part C: ?edit=<id> → 拉取该笔记并直接进入编辑器（一次挂载效果）
  useEffect(() => {
    if (!editNoteId) return;
    let active = true;
    apiGet<NoteItem>(`/notes/${editNoteId}`)
      .then((note) => { if (active) setEditing(note); })
      .catch(() => { /* 已删除/无权限时留在列表 */ });
    return () => { active = false; };
  }, [editNoteId]);

  // One filter identity: chemical takes precedence over reaction (P-8).
  const filterKey = filterChemicalId != null ? "chemical" : filterReactionId != null ? "reaction" : null;
  const filterId = filterChemicalId ?? filterReactionId;

  function listHref(targetPage: number): string {
    return withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(visibility, filterChemicalId, filterReactionId, targetPage)) }).toString()}`, locale);
  }

  /** §6 Step 9：筛选用 Segmented（全部/私有/公开），仍走 URL 参数（可分享/SSR 预取一致） */
  function switchVisibility(value: NoteVisibility) {
    if (value === visibility) return;
    router.push(withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(value, filterChemicalId, filterReactionId)) }).toString()}`, locale));
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

  function openCreate() {
    setEditing(null);
    setCreateContext({ chemicalIds: [], reactionIds: [] });
    setCreating(true);
  }

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

  /** IX-3：删除前确认弹窗（问句标题 + 对象摘录 + 具体动作按钮）；成功/失败都
   * 用 Toast 反馈；失败保留原列表数据（R6：面板保持可交互，不整页报错）。 */
  async function remove(note: NoteItem) {
    const excerpt = note.content.length > 24 ? `${note.content.slice(0, 24)}…` : note.content;
    const ok = await confirm({
      title: t.notes.deleteTitle,
      body: t.notes.deleteBody(excerpt),
      confirmLabel: t.notes.deleteLabel,
      tone: "danger",
    });
    if (!ok) return;
    setActionError(null);
    try {
      await apiDelete(`/notes/${note.id}`);
      if (editing?.id === note.id) setEditing(null);
      toast.success(t.notes.deleted);
      await load();
    } catch (err) {
      toast.error(t.common.deleteFailed);
      setActionError(t.notes.deleteFailed);
      setError(err);
    }
  }

  const filterOptions = [
    { value: "all" as const, label: t.me.filterAll },
    { value: "private" as const, label: t.common.private },
    { value: "public" as const, label: t.common.public },
  ];

  return (
    <section className="wb-panel wb-notes">
      <PanelHeading
        title={t.nav.tabNotes}
        subtitle={t.me.notesHint}
        count={state === "ready" ? data.total : "—"}
        unit={t.me.unitNote}
        action={<Button variant="primary" size="sm" onClick={openCreate}>{t.me.notesNew}</Button>}
      />

      <Segmented
        ariaLabel={t.me.notesFilter}
        options={filterOptions}
        value={visibility}
        onChange={(value) => switchVisibility(value)}
      />

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

      {state === "loading" && <PanelLoading variant="list" rows={4} />}
      {state === "error" && <PanelError error={error} />}
      {/* R6: delete failure keeps the list mounted with a recoverable state */}
      {actionError && state !== "error" && (
        <p className="wb-panel-inline-error" role="alert">{actionError}</p>
      )}
      {state === "ready" && (data.items.length ? (
        <div className="wb-row-list">
          {data.items.map((note) => (
            <WbListRow
              key={note.id}
              href={`/note/${note.id}`}
              icon={<IconNote />}
              title={noteHeadline(note.content) || t.notes.detailTitle}
              meta={
                <>
                  <VisibilityTag visibility={note.visibility} t={t} />
                  {note.chemical_ids.slice(0, 2).map((cid) => <EntityBadge key={`c${cid}`} kind="chemical" id={cid} size="xs" ariaLabel={t.common.hcidLabel(cid)} />)}
                  {note.reaction_ids.slice(0, 2).map((rid) => <EntityBadge key={`r${rid}`} kind="reaction" id={rid} size="xs" ariaLabel={t.common.hridLabel(rid)} />)}
                  <time dateTime={note.updated_at}>{relativeTime(note.updated_at, locale)}</time>
                </>
              }
              side={
                <>
                  <span>{new Date(note.updated_at).toLocaleDateString(locale)}</span>
                  <span className="wb-row-actions">
                    <Button variant="ghost" size="sm" onClick={() => { setCreating(false); setEditing(note); }}>{t.common.edit}</Button>
                    <Button variant="danger-quiet" size="sm" onClick={() => void remove(note)}>{t.common.delete}</Button>
                  </span>
                </>
              }
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<IconNote />}
          title={filterKey ? t.notes.filterEmpty : t.me.notesEmpty}
          action={{ label: t.me.notesNew, onClick: openCreate }}
        />
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
