"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiDelete } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";

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
  return <div className="owner-actions"><Link className="button secondary small" href={withLocale(`/submit?reaction=${reactionId}`, locale)}>{t.common.edit}</Link><button className="button danger small" onClick={remove} disabled={busy}>{busy ? t.common.deleteInProgress : t.common.delete}</button></div>;
}
