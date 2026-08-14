"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiDelete } from "@/lib/api";
import t from "@/lib/i18n";

export function ReactionOwnerActions({ reactionId }: { reactionId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm(t.reaction.confirmDelete(reactionId))) return;
    setBusy(true);
    try {
      await apiDelete(`/reactions/${reactionId}`);
      router.push("/aichem"); router.refresh(); return;
    } catch {
      setBusy(false);
    }
  }
  return <div className="owner-actions"><Link className="button secondary small" href={`/submit?reaction=${reactionId}`}>{t.common.edit}</Link><button className="button danger small" onClick={remove} disabled={busy}>{busy ? t.common.deleteInProgress : t.common.delete}</button></div>;
}
