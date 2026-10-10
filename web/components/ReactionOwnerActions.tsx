"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiDelete } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { Button } from "@/components/ui/Button";

/**
 * ReactionOwnerActions — 本人反应操作行（v1.7 Step 7 §9.2，Step 8 收敛为两项）。
 *
 * 编辑 / 删除（danger-quiet，经 useConfirm）。原「可见性切换」按钮同样跳
 * /submit 编辑表单（无独立切换端点），与「编辑」完全重复——Step 8 删除，
 * 可见性在编辑表单内修改。
 */
export function ReactionOwnerActions({ reactionId }: { reactionId: number }) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const confirm = useConfirm();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  /** IX-3：确认弹窗（问句标题 + HRID 与后果 + 具体动作按钮）；成功 Toast 后回工作台，失败 Toast 保留页面 */
  async function remove() {
    const ok = await confirm({
      title: t.reaction.deleteTitle,
      body: t.reaction.deleteBody(reactionId),
      confirmLabel: t.reaction.deleteLabel,
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await apiDelete(`/reactions/${reactionId}`);
      toast.success(t.reaction.deleted);
      router.push(withLocale("/aichem", locale)); router.refresh(); return;
    } catch {
      setBusy(false);
      toast.error(t.common.deleteFailed);
    }
  }
  const editHref = withLocale(`/submit?reaction=${reactionId}`, locale);
  return (
    <div className="owner-actions">
      <Button variant="secondary" href={editHref}>{t.common.edit}</Button>
      <Button variant="danger-quiet" onClick={remove} loading={busy}>{t.common.delete}</Button>
    </div>
  );
}
