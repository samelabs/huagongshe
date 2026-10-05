"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiDelete } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

export function ReactionOwnerActions({ reactionId }: { reactionId: number }) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm(t.reaction.confirmDelete(reactionId))) return;
    setBusy(true);
    try {
      await apiDelete(`/reactions/${reactionId}`);
      router.push(withLocale("/aichem", locale)); router.refresh(); return;
    } catch {
      setBusy(false);
    }
  }
  return <div className="owner-actions"><Link className="button secondary small" href={withLocale(`/submit?reaction=${reactionId}`, locale)}>{t.common.edit}</Link><button className="button danger small" onClick={remove} disabled={busy}>{busy ? t.common.deleteInProgress : t.common.delete}</button></div>;
}
