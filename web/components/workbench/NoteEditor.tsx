"use client";

import { useMemo, useRef, useState } from "react";
import { apiPost, apiPut, ApiError } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { Button } from "@/components/ui/Button";
import { Field, Select, Textarea } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { EntityReferencePicker } from "./EntityReferencePicker";
import { SaveStatus, type SaveStatusKind } from "./SaveStatus";
import { useUnsavedGuard } from "./useUnsavedGuard";
import type { NoteItem } from "./types";

/**
 * NoteEditor — 手动保存（沿用现有保存方式，IX-5 只加状态与拦截）：
 * - 标题旁显示保存状态：已保存 / 保存中 / 未保存的修改 / 保存失败（带重试）。
 * - 有未保存修改时：站内路由切换弹 useConfirm（放弃修改，danger），
 *   刷新/关闭走 beforeunload；「取消」按钮同样先确认。
 * - 保存失败保留输入内容，Notice err + 重试。
 * - 字段用 Field 组件（label 在上）。
 */
export function NoteEditor({
  note,
  initialChemicalIds = [],
  initialReactionIds = [],
  onSaved,
  onCancel,
}: {
  note?: NoteItem | null;
  initialChemicalIds?: number[];
  initialReactionIds?: number[];
  onSaved: (note: NoteItem) => void;
  onCancel: () => void;
}) {
  const t = useDictionary();
  const confirm = useConfirm();
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

  useUnsavedGuard(dirty);

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
      onSaved(saved);
    } catch (err) {
      // v1.7.0 L2(+补正): 先按 HTTP 状态区分会话/限流 — 与失败原因一致;
      // 400 引用校验按 kind 机器码映射五语言分类提示; 其余未知失败安全
      // 回退 notesSaveFailed, 不展示原始技术错误或中文原文。
      // 输入内容全部保留（IX-5：保存失败不清空输入）。
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError(t.me.notesSessionExpired);
        } else if (err.status === 429) {
          setError(t.search.errRateLimit);
        } else if (err.status === 400 && err.detailKind) {
          const byKind = t.me.notesRefError[err.detailKind as keyof typeof t.me.notesRefError];
          setError(byKind ?? t.me.notesSaveFailed);
        } else {
          setError(t.me.notesSaveFailed);
        }
      } else {
        setError(t.me.notesSaveFailed);
      }
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
        tone: "danger",
      });
      if (!ok) return;
    }
    onCancel();
  }

  return (
    <form className="wb-note-editor" onSubmit={save}>
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
