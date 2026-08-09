"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import t from "@/lib/i18n";

export function ReactionOwnerActions({ reactionId }: { reactionId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm(`确定永久删除 HRID ${reactionId}？关联的化合物不会被删除。`)) return;
    setBusy(true);
    const response = await fetch(`/api/reactions/${reactionId}`, { method: "DELETE" });
    if (response.ok) { router.push("/aichem"); router.refresh(); return; }
    setBusy(false);
  }
  return <div className="owner-actions"><Link className="button secondary small" href={`/submit?reaction=${reactionId}`}>{t.common.edit}</Link><button className="button danger small" onClick={remove} disabled={busy}>{busy ? t.common.deleteInProgress : t.common.delete}</button></div>;
}
