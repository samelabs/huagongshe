"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiPost, apiPut, ApiError } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { Button } from "@/components/ui/Button";
import { Field, Select, Textarea } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { EntityReferencePicker } from "./EntityReferencePicker";
import { SaveStatus, type SaveStatusKind } from "./SaveStatus";
import { useUnsavedGuard } from "./useUnsavedGuard";
import type { NoteItem } from "./types";

/**
 * NoteEditor — 手动保存（沿用现有保存方式， 只加状态与拦截）：
 * - 标题旁显示保存状态：已保存 / 保存中 / 未保存的修改 / 保存失败（带重试）。
 * - 有未保存修改或保存在途时：站内路由切换/浏览器后退弹 useConfirm
 * （放弃修改，danger），「取消」按钮同样先确认；父面板经 onGuardChange
 * 同步该状态拦截「新建/切编辑/切可见性」。
 * - 保存失败保留输入内容，Toast err + Notice err + 重试。
 * - 字段用 Field 组件（label 在上）。
 */
export function NoteEditor({
  note,
  initialChemicalIds = [],
  initialReactionIds = [],
  onSaved,
  onCancel,
  onGuardChange,
  resetNonce = 0,
  session = 0,
}: {
  note?: NoteItem | null;
  initialChemicalIds?: number[];
  initialReactionIds?: number[];
  onSaved: (note: NoteItem, session: number) => void;
  onCancel: () => void;
  /** 编辑器上报「有不可丢失状态」的细分：脏草稿 / 保存请求进行中 ——
   * NotesPanel 分别给出如实的确认文案（保存中切换要说保存会继续完成）。 */
  onGuardChange?: (state: { dirty: boolean; busy: boolean }) => void;
  /** 父面板「确认放弃后重开」递增号：key 不变（同一笔记）时靠它重置草稿 */
  resetNonce?: number;
  /** 本次编辑会话号：随 onSaved 回传，父面板只让发起保存的会话收尾 */
  session?: number;
}) {
  const t = useDictionary();
  const confirm = useConfirm();
  const toast = useToast();
  const [visibility, setVisibility] = useState<"private" | "public">(note?.visibility ?? "private");
  const [content, setContent] = useState(note?.content ?? "");
  const [chemicalIds, setChemicalIds] = useState<number[]>(note?.chemical_ids ?? initialChemicalIds);
  const [reactionIds, setReactionIds] = useState<number[]>(note?.reaction_ids ?? initialReactionIds);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  /** 初始快照：dirty = 与快照不一致（完全等于快照即无可丢失的修改） */
  const baseline = useRef({
    visibility: note?.visibility ?? "private",
    content: note?.content ?? "",
    chemicalIds: (note?.chemical_ids ?? initialChemicalIds).join(","),
    reactionIds: (note?.reaction_ids ?? initialReactionIds).join(","),
  });
  const changed =
    visibility !== baseline.current.visibility
    || content !== baseline.current.content
    || chemicalIds.join(",") !== baseline.current.chemicalIds
    || reactionIds.join(",") !== baseline.current.reactionIds;
  const dirty = !busy && changed;
  /** 保存在途同样是「有不可丢失的状态」——拦截保护不得被撤掉 */
  const guard = dirty || busy;

  useUnsavedGuard(guard, busy
    ? { title: t.editor.savingTitle, body: t.editor.savingBody, confirmLabel: t.editor.savingConfirm, cancelLabel: t.editor.savingCancel }
    : { title: t.editor.unsavedTitle, body: t.editor.unsavedBody, confirmLabel: t.editor.unsavedConfirm, cancelLabel: t.editor.unsavedCancel });

  useEffect(() => { onGuardChange?.({ dirty, busy }); }, [dirty, busy, onGuardChange]);

  /** key 保持 P1C 契约串（edit-<id>/new-*），同一笔记确认放弃后
   * 重开（key 不变）由 resetNonce 触发内部草稿重置 —— 等价于重挂载。 */
  useEffect(() => {
    setVisibility(note?.visibility ?? "private");
    setContent(note?.content ?? "");
    setChemicalIds(note?.chemical_ids ?? initialChemicalIds);
    setReactionIds(note?.reaction_ids ?? initialReactionIds);
    baseline.current = {
      visibility: note?.visibility ?? "private",
      content: note?.content ?? "",
      chemicalIds: (note?.chemical_ids ?? initialChemicalIds).join(","),
      reactionIds: (note?.reaction_ids ?? initialReactionIds).join(","),
    };
    setError("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetNonce]);

  const status: SaveStatusKind | null = useMemo(() => {
    if (busy) return "saving";
    if (error) return "failed";
    if (dirty) return "dirty";
    if (note) return "saved";
    return null;
  }, [busy, error, dirty, note]);

  async function doSave() {
    const body = {
      visibility,
      content: content.trim(),
      chemical_ids: chemicalIds,
      reaction_ids: reactionIds,
    };
    if (!body.content) return;
    setBusy(true);
    setError("");
    try {
      const saved = note
        ? await apiPut<NoteItem>(`/notes/${note.id}`, JSON.stringify(body))
        : await apiPost<NoteItem>("/notes", JSON.stringify(body));
      // 带上发起保存的会话号 —— 编辑器若已被确认切换/关闭（unmount 后
      // 此闭包仍会执行），父面板靠它识别这是过期会话的迟到回执。
      onSaved(saved, session);
    } catch (err) {
      // 先按 HTTP 状态区分会话/限流 — 与失败原因一致;
      // 400 引用校验按 kind 机器码映射五语言分类提示; 其余未知失败安全
      // 回退 notesSaveFailed, 不展示原始技术错误或中文原文。
      // 输入内容全部保留（保存失败不清空输入）；
      // Toast err 即时反馈 + Notice err 常驻带重试（/）。
      let message = t.me.notesSaveFailed;
      if (err instanceof ApiError) {
        if (err.status === 401) message = t.me.notesSessionExpired;
        else if (err.status === 429) message = t.search.errRateLimit;
        else if (err.status === 400 && err.detailKind) {
          const byKind = t.me.notesRefError[err.detailKind as keyof typeof t.me.notesRefError];
          message = byKind ?? t.me.notesSaveFailed;
        }
      }
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void doSave();
  }

  /** 有未保存修改时，取消也要确认（与离开拦截同一语义） */
  async function cancel() {
    if (busy) return;
    if (dirty) {
      const ok = await confirm({
        title: t.editor.unsavedTitle,
        body: t.editor.unsavedBody,
        confirmLabel: t.editor.unsavedConfirm,
        cancelLabel: t.editor.unsavedCancel,
        tone: "danger",
      });
      if (!ok) return;
    }
    onCancel();
  }

  return (
    <form method="post" className="wb-note-editor" onSubmit={save}>
      <div className="wb-note-editor-head">
        <strong>{note ? t.me.notesEdit : t.me.notesNew}</strong>
        <div className="wb-note-editor-head-side">
          <SaveStatus status={status} t={t} onRetry={() => void doSave()} />
          <Field label={t.editor.visibilityLabel} className="wb-note-editor-visibility" htmlFor="wb-note-visibility">
            <Select id="wb-note-visibility" value={visibility} onChange={(event) => setVisibility(event.target.value as "private" | "public")} disabled={busy}>
              <option value="private">{t.common.private}</option>
              <option value="public">{t.common.public}</option>
            </Select>
          </Field>
        </div>
      </div>
      <Field label={t.editor.contentLabel} htmlFor="wb-note-content">
        <Textarea
          id="wb-note-content"
          rows={8}
          maxLength={30000}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder={t.me.notesPlaceholder}
          autoFocus
          disabled={busy}
        />
      </Field>
      <EntityReferencePicker
        chemicalIds={chemicalIds}
        reactionIds={reactionIds}
        onChange={({ chemicalIds: nextChemicals, reactionIds: nextReactions }) => {
          setChemicalIds(nextChemicals);
          setReactionIds(nextReactions);
        }}
        disabled={busy}
      />
      {error && (
        <Notice tone="err" action={{ label: t.editor.retry, onClick: () => void doSave() }}>
          {error}
        </Notice>
      )}
      <div className="wb-note-editor-actions">
        <Button variant="ghost" type="button" onClick={() => void cancel()} disabled={busy}>{t.me.notesCancel}</Button>
        <Button variant="primary" type="submit" loading={busy} disabled={!content.trim()}>
          {t.me.notesSave}
        </Button>
      </div>
    </form>
  );
}
