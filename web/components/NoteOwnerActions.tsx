"use client";

/**
 * NoteOwnerActions — 笔记详情页本人操作（v1.7 Step 7 Part C）。
 * 编辑（secondary sm）→ 工作台笔记面板 ?edit=<id> 直接打开编辑器；
 * 删除（danger-quiet sm）经 useConfirm → DELETE /notes/{id}（现有端点）
 * → Toast + 跳回工作台笔记列表。
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiDelete } from "@/lib/api";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { Button } from "@/components/ui/Button";

export function NoteOwnerActions({ noteId, ownerUsername, excerpt }: { noteId: number; ownerUsername: string; excerpt: string }) {
  const router = useRouter();
  const { user } = useAccount();
  const t = useDictionary();
  const locale = useLocale();
  const confirm = useConfirm();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  // 本人判定：全局会话（AccountContext）与笔记作者 username 比对；
  // GET /notes/{id} 不暴露 is_owner，也不为此新增请求。
  if (user?.username !== ownerUsername) return null;

  async function remove() {
    const ok = await confirm({
      title: t.notes.deleteTitle,
      body: t.notes.deleteBody(excerpt),
      confirmLabel: t.notes.deleteLabel,
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await apiDelete(`/notes/${noteId}`);
      toast.success(t.notes.deleted);
      router.push(withLocale("/aichem?tab=notes", locale));
      router.refresh();
    } catch {
      setBusy(false);
      toast.error(t.common.deleteFailed);
    }
  }

  return (
    <div className="note-owner-actions">
      <Button variant="secondary" size="sm" href={withLocale(`/aichem?tab=notes&edit=${noteId}`, locale)}>{t.notes.editInWorkbench}</Button>
      <Button variant="danger-quiet" size="sm" onClick={remove} loading={busy}>{t.common.delete}</Button>
    </div>
  );
}
