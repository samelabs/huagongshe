"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EntityId } from "@/components/EntityId";
import { SamelabsNav } from "@/components/SamelabsNav";
import t from "@/lib/i18n";

type ReactionRow = { id: number; reaction_smiles: string; visibility: string; moderation_status: "visible" | "hidden"; username: string; display_name: string; created_at: string };

export function SamelabsReactions() {
  const [reactions, setReactions] = useState<ReactionRow[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  async function load() {
    const res = await fetch("/api/admin/reactions?limit=100", { cache: "no-store" });
    if (res.status === 401 || res.status === 403) { setError(t.admin.noPermission); return; }
    if (res.ok) setReactions(await res.json());
  }

  useEffect(() => { load(); }, []);

  async function toggle(id: number, status: "visible" | "hidden") {
    setError(""); setBusyId(id);
    try {
      const res = await fetch(`/api/admin/reactions/${id}/moderation`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: status === "visible" ? "hidden" : "visible" }),
      });
      if (!res.ok) throw new Error();
      await load();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  if (error && reactions.length === 0) return <div className="notice error">{error}</div>;

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.reactionsKicker}</p>
      <h1>{t.admin.reactionsTitle}</h1>
    </header>
    <div className="settings-layout">
      <SamelabsNav />
      <div className="settings-content">
        {error && <div className="notice error">{error}</div>}
        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.reactionsListTitle}</h2></div>
            <span>{t.admin.reactionCount(reactions.length)}</span>
          </div>
          <div className="admin-table reaction-admin-list">
            {reactions.map((r) => <article key={r.id}>
              <div>
                <EntityId kind="reaction" id={r.id} />
                <span>{r.display_name} · {r.visibility === "public" ? t.admin.publicLabel : t.admin.privateLabel}</span>
              </div>
              <span className={`status ${r.moderation_status}`}>{r.moderation_status === "visible" ? t.admin.statusVisible : t.admin.statusHidden}</span>
              <button className="text-button" disabled={busyId === r.id} onClick={() => toggle(r.id, r.moderation_status)}>
                {busyId === r.id ? "…" : r.moderation_status === "visible" ? t.admin.actionHide : t.admin.actionShow}
              </button>
            </article>)}
          </div>
        </section>
      </div>
    </div>
  </>;
}
