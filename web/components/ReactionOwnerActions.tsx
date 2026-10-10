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
 * ReactionOwnerActions — 本人反应操作行（v1.7 Step 7 §9.2）。
 *
 * 编辑 / 可见性切换（secondary）→ 既有 /submit 编辑表单（可见性在表单内
 * 修改——现有逻辑，无独立切换端点）；删除（danger-quiet）经 useConfirm。
 * 内部改用 ui/Button 组件，对外接口（reactionId）不变。
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
      <Button variant="secondary" href={editHref}>{t.reaction.visibilityToggle}</Button>
      <Button variant="danger-quiet" onClick={remove} loading={busy}>{t.common.delete}</Button>
    </div>
  );
}
