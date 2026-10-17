"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { EntityId } from "@/components/shared/EntityId";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Segmented } from "@/components/ui/Segmented";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { IconNote, IconPencil, IconTrash } from "@/components/ui/icons";
import { apiDelete, apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { NoteEditor } from "../NoteEditor";
import { PanelError, PanelHeading, PanelLoading, Pagination, SlowNotice, VisibilityTag, WbListRow, noteListPresentation, relativeTime } from "../shared";
import type { LoadState, NoteItem, NoteResponse, NoteVisibility, PanelProps } from "../types";
import { TextLink } from "@/components/ui/TextLink";

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
  /** SMK-001：每次「确认放弃旧草稿 → 打开新编辑上下文」递增，强制 NoteEditor
   *  重挂载（key 变化）——否则同一 key 下编辑器实例复用，旧草稿残留。 */
  const [editorNonce, setEditorNonce] = useState(0);
  /** BX-A1：编辑会话号 —— 每次打开编辑器（新建/切编辑/?edit=/?new=）递增。
   *  NoteEditor 的保存回执带发起时的会话号；会话已换人时只刷新列表，
   *  不动当前编辑器（A 保存中途确认切到 B，A 完成后 B 必须原样在）。 */
  const editorSessionRef = useRef(0);
  const [editorSession, setEditorSession] = useState(0);
  const beginEditorSession = useCallback(() => {
    editorSessionRef.current += 1;
    setEditorSession(editorSessionRef.current);
  }, []);
  /** SMK-001：编辑器「有不可丢失状态」的细分（脏草稿/保存在途）——BX-A1
   *  起保存中切换给如实的确认文案（保存会继续完成） */
  const [editorGuard, setEditorGuard] = useState<{ dirty: boolean; busy: boolean }>({ dirty: false, busy: false });
  const handleGuardChange = useCallback((value: { dirty: boolean; busy: boolean }) => setEditorGuard(value), []);
  const mounted = useRef(false);
  const latestLoad = useRef(0);

  // 编辑器关闭后复位面板侧拦截状态
  useEffect(() => {
    if (!creating && !editing) setEditorGuard({ dirty: false, busy: false });
  }, [creating, editing]);

  /** SMK-001：切换编辑上下文前的统一丢稿拦截（新建/切编辑/切可见性三条
   *  不经过 <a> 的路径）。BX-A1：保存在途时文案如实 —— 保存会继续完成。
   *  返回 true = 可以继续切换。 */
  async function guardDraft(): Promise<boolean> {
    if (!editorGuard.dirty && !editorGuard.busy) return true;
    if (editorGuard.busy) {
      return confirm({
        title: t.editor.savingTitle,
        body: t.editor.savingBody,
        confirmLabel: t.editor.savingConfirm,
        cancelLabel: t.editor.savingCancel,
        tone: "danger",
      });
    }
    return confirm({
      title: t.editor.unsavedTitle,
      body: t.editor.unsavedBody,
      confirmLabel: t.editor.unsavedConfirm,
      cancelLabel: t.editor.unsavedCancel,
      tone: "danger",
    });
  }

  // Step 7 Part C: ?edit=<id> → 拉取该笔记并直接进入编辑器（一次挂载效果）
  useEffect(() => {
    if (!editNoteId) return;
    let active = true;
    beginEditorSession();
    apiGet<NoteItem>(`/notes/${editNoteId}`)
      .then((note) => { if (active) setEditing(note); })
      .catch(() => { /* 已删除/无权限时留在列表 */ });
    return () => { active = false; };
  }, [editNoteId, beginEditorSession]);

  // One filter identity: chemical takes precedence over reaction (P-8).
  const filterKey = filterChemicalId != null ? "chemical" : filterReactionId != null ? "reaction" : null;
  const filterId = filterChemicalId ?? filterReactionId;

  function listHref(targetPage: number): string {
    return withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(visibility, filterChemicalId, filterReactionId, targetPage)) }).toString()}`, locale);
  }

  /** DESIGN_SYSTEM 3.7 / 6.7：筛选用 Segmented（全部/私有/公开），仍走 URL 参数（可分享/SSR 预取一致）。
   *  SMK-017：编辑器有未保存内容时先确认（router.push 不经过 <a> 拦截）。 */
  async function switchVisibility(value: NoteVisibility) {
    if (value === visibility) return;
    if (!(await guardDraft())) return;
    setCreating(false);
    setEditing(null);
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
      beginEditorSession();
      setCreating(true);
    }
  }, [createOpen, initialChemicalId, initialReactionId, beginEditorSession]);

  function openCreate() {
    void (async () => {
      if (!(await guardDraft())) return;
      setEditing(null);
      setCreateContext({ chemicalIds: [], reactionIds: [] });
      setEditorNonce((n) => n + 1);
      beginEditorSession();
      setCreating(true);
    })();
  }

  function closeEditor() {
    setCreating(false);
    setEditing(null);
    if (createOpen) router.replace(listHref(1));
  }

  /** R3: never strand the user on a list where the note they just saved
   * cannot appear. page=1 + the list can show it → refresh in place;
   * otherwise navigate to page 1 of the filter with the saved note's
   * own visibility (a private note saved under a public filter etc.).
   * BX-A1：保存回执只作用于发起本次保存的编辑会话 —— 保存期间用户确认
   * 切换到另一编辑器（或已关闭）时，这里仅刷新列表，不动当前编辑器、
   * 不导航（迟到的 setEditing(null)/router.replace 会把新编辑器关掉）。 */
  async function handleSaved(saved: NoteItem, session: number) {
    const visibleHere = visibility === "all" || visibility === saved.visibility;
    const inFilter = filterKey === null
      || (filterKey === "chemical" && saved.chemical_ids.includes(filterChemicalId!))
      || (filterKey === "reaction" && saved.reaction_ids.includes(filterReactionId!));
    if (session !== editorSessionRef.current) {
      // 过期会话的保存回执：当前列表若能直接反映该笔记就原地刷新，否则留待
      // 下次筛选/翻页自然刷新 —— 绝不动用户正在用的编辑器。
      if (page === 1 && visibleHere && inFilter) await load();
      return;
    }
    const created = creating && !editing;
    setCreating(false);
    setEditing(null);
    if (created) setCreateContext({ chemicalIds: [], reactionIds: [] });

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
        count={state === "ready" ? data.total : undefined}
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
          <TextLink href={withLocale(`/aichem?${new URLSearchParams({ tab: "notes", ...Object.fromEntries(listParams(visibility)) }).toString()}`, locale)}>
            {t.notes.filterClear}
          </TextLink>
        </div>
      )}

      {(creating || editing) && (
        <NoteEditor
          key={editing ? `edit-${editing.id}` : `new-${editorNonce}`}
          note={editing}
          initialChemicalIds={!editing ? createContext.chemicalIds : []}
          initialReactionIds={!editing ? createContext.reactionIds : []}
          onCancel={closeEditor}
          onSaved={handleSaved}
          onGuardChange={handleGuardChange}
          resetNonce={editorNonce}
          session={editorSession}
        />
      )}

      {state === "loading" && <><PanelLoading variant="list" rows={4} /><SlowNotice active onRetry={() => void load()} /></>}
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
              title={noteListPresentation(note, t).title}
              summary={noteListPresentation(note, t).summary}
              meta={
                <>
                  <VisibilityTag visibility={note.visibility} t={t} />
                  {note.chemical_ids.slice(0, 2).map((cid) => <EntityBadge key={`c${cid}`} kind="chemical" id={cid} size="xs" ariaLabel={t.common.hcidLabel(cid)} />)}
                  {note.reaction_ids.slice(0, 2).map((rid) => <EntityBadge key={`r${rid}`} kind="reaction" id={rid} size="xs" ariaLabel={t.common.hridLabel(rid)} />)}
                </>
              }
              side={
                <>
                  <time dateTime={note.updated_at}>{relativeTime(note.updated_at, locale)}</time>
                  <span className="wb-row-actions">
                    <Button variant="ghost" size="sm" iconOnly aria-label={t.common.edit} onClick={() => { void (async () => {
                      if (!(await guardDraft())) return;
                      setCreating(false);
                      setEditing(note);
                      setEditorNonce((n) => n + 1);
                      beginEditorSession();
                    })(); }}><IconPencil /></Button>
                    <Button variant="ghost" size="sm" iconOnly className="wb-action-danger" aria-label={t.common.delete} onClick={() => void remove(note)}><IconTrash /></Button>
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
        >
          {filterKey ? undefined : t.me.notesEmptyDesc}
        </EmptyState>
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
