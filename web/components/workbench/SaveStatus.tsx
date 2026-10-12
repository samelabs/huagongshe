"use client";

/**
 * SaveStatus — IX-5 保存状态指示（NoteEditor / SubmissionForm 共用）：
 * 已保存（ok 点）/ 保存中（转圈）/ 未保存的修改（warn 点）/ 保存失败
 * （err 点 + 「重试」）。aria-live 播报状态变化。
 */
import { Button } from "@/components/ui/Button";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

export type SaveStatusKind = "saved" | "saving" | "dirty" | "failed";

export function SaveStatus({ status, t, onRetry }: {
  status: SaveStatusKind | null;
  t: Dictionary;
  onRetry?: () => void;
}) {
  if (!status) return null;
  const label: Record<SaveStatusKind, string> = {
    saved: t.editor.saved,
    saving: t.editor.saving,
    dirty: t.editor.dirty,
    failed: t.editor.failed,
  };
  return (
    <span className={`wb-save-status ${status}`} role="status" aria-live="polite" aria-label={t.editor.statusLabel}>
      {status === "saving"
        ? <i className="hg-spin" aria-hidden="true" />
        : <i className="wb-save-dot" aria-hidden="true" />}
      {label[status]}
      {status === "failed" && onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>{t.editor.retry}</Button>
      )}
    </span>
  );
}
