"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type Status = "pending" | "accepted" | "rejected";
type ChemicalSubmission = {
  id: number; username: string; chemical_id: number | null; submitted_smiles: string | null;
  submitted_cas: string | null; submitted_name: string | null; note: string | null;
  status: Status; review_note: string | null; created_at: string;
};
type Participant = { position: number; role: string; submitted_smiles: string; canonical_smiles: string; yield_percent: number | null };
type ReactionSubmission = {
  id: number; username: string; reaction_id: number | null; reaction_smiles: string;
  procedure_details: string; conditions_detail: string | null; temperature_value: number | null;
  temperature_unit: string | null; duration_value: number | null; duration_unit: string | null;
  ph: number | null; atmosphere: string | null; pressure_value: number | null; pressure_unit: string | null;
  safety_notes: string | null; doi: string | null; patent: string | null; source_url: string | null;
  note: string | null; status: Status; review_note: string | null; created_at: string;
  participants: Participant[];
};
type Queue = { chemicals: ChemicalSubmission[]; reactions: ReactionSubmission[] };

const roleName: Record<string, string> = {
  REACTANT: "反应物", PRODUCT: "产物", REAGENT: "试剂", CATALYST: "催化剂", SOLVENT: "溶剂",
};

export function AdminReview() {
  const [status, setStatus] = useState<Status>("pending");
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setError("");
    const response = await fetch(`/api/community/admin/submissions?status=${status}`, { cache: "no-store" });
    if (!response.ok) {
      setQueue(null); setError(response.status === 403 ? "当前账号没有审核权限" : response.status === 401 ? "请先登录审核账号" : "审核队列读取失败"); return;
    }
    setQueue(await response.json());
  }, [status]);

  useEffect(() => { load(); }, [load]);

  async function review(kind: "chemical" | "reaction", id: number, decision: "accept" | "reject") {
    const key = `${kind}-${id}`;
    const reviewNote = (notes[key] || "").trim();
    if (decision === "reject" && !reviewNote) { setError("拒绝提交必须填写审核说明"); return; }
    if (decision === "accept" && !window.confirm("确认结构和来源无误，并写入核心数据？")) return;
    setBusy(key); setError("");
    const response = await fetch(`/api/community/admin/${kind}-submissions/${id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, review_note: reviewNote || null }),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : "审核操作失败";
      setError(detail); setBusy(""); return;
    }
    setBusy(""); await load();
  }

  return (
    <>
      <div className="tabs admin-tabs">
        {(["pending", "accepted", "rejected"] as Status[]).map((value) => (
          <button type="button" key={value} className={status === value ? "active" : ""} onClick={() => setStatus(value)}>
            {value === "pending" ? "待审核" : value === "accepted" ? "已接受" : "已拒绝"}
          </button>
        ))}
      </div>
      {error && <p className="form-message bad">{error}</p>}
      {queue && queue.chemicals.length === 0 && queue.reactions.length === 0 && <p className="empty-state">当前队列为空。</p>}
      {queue?.chemicals.map((item) => {
        const key = `chemical-${item.id}`;
        return (
          <article className="review-card" key={key}>
            <header><div><strong>化合物 #{item.id}</strong><span>提交人 {item.username}</span></div>{item.chemical_id && <Link href={`/chemical/${item.chemical_id}`}>匹配 #{item.chemical_id}</Link>}</header>
            <dl>
              {item.submitted_name && <><dt>名称</dt><dd>{item.submitted_name}</dd></>}
              {item.submitted_smiles && <><dt>SMILES</dt><dd className="mono">{item.submitted_smiles}</dd></>}
              {item.submitted_cas && <><dt>CAS</dt><dd>{item.submitted_cas}</dd></>}
              {item.note && <><dt>说明</dt><dd>{item.note}</dd></>}
            </dl>
            <ReviewActions itemKey={key} status={item.status} note={notes[key] ?? item.review_note ?? ""} busy={busy === key}
              onNote={(value) => setNotes((current) => ({ ...current, [key]: value }))}
              onAccept={() => review("chemical", item.id, "accept")} onReject={() => review("chemical", item.id, "reject")} />
          </article>
        );
      })}
      {queue?.reactions.map((item) => {
        const key = `reaction-${item.id}`;
        const grouped = item.participants.reduce<Record<string, Participant[]>>((result, participant) => {
          (result[participant.role] ||= []).push(participant);
          return result;
        }, {});
        return (
          <article className="review-card reaction-review" key={key}>
            <header><div><strong>反应 #{item.id}</strong><span>提交人 {item.username}</span></div>{item.reaction_id && <Link href={`/reaction/${item.reaction_id}`}>目标 #{item.reaction_id}</Link>}</header>
            <div className="review-participants">
              {Object.entries(grouped).map(([role, participants]) => (
                <section key={role}><h3>{roleName[role] || role}</h3>{participants?.map((participant) => <p className="mono" key={participant.position}>{participant.canonical_smiles}{participant.yield_percent != null ? ` · ${participant.yield_percent}%` : ""}</p>)}</section>
              ))}
            </div>
            <dl>
              <dt>过程</dt><dd>{item.procedure_details}</dd>
              {item.conditions_detail && <><dt>条件</dt><dd>{item.conditions_detail}</dd></>}
              {(item.temperature_value != null || item.duration_value != null || item.ph != null || item.atmosphere) && <><dt>标准条件</dt><dd>{[
                item.temperature_value != null ? `${item.temperature_value} ${item.temperature_unit}` : null,
                item.duration_value != null ? `${item.duration_value} ${item.duration_unit}` : null,
                item.ph != null ? `pH ${item.ph}` : null, item.atmosphere,
              ].filter(Boolean).join(" · ")}</dd></>}
              {(item.doi || item.patent || item.source_url) && <><dt>来源</dt><dd>{[item.doi, item.patent, item.source_url].filter(Boolean).join(" · ")}</dd></>}
              {item.safety_notes && <><dt>安全</dt><dd>{item.safety_notes}</dd></>}
              {item.note && <><dt>说明</dt><dd>{item.note}</dd></>}
            </dl>
            <details><summary>RDKit 反应表达</summary><p className="mono">{item.reaction_smiles}</p></details>
            <ReviewActions itemKey={key} status={item.status} note={notes[key] ?? item.review_note ?? ""} busy={busy === key}
              onNote={(value) => setNotes((current) => ({ ...current, [key]: value }))}
              onAccept={() => review("reaction", item.id, "accept")} onReject={() => review("reaction", item.id, "reject")} />
          </article>
        );
      })}
    </>
  );
}

function ReviewActions({ status, note, busy, onNote, onAccept, onReject }: {
  itemKey: string; status: Status; note: string; busy: boolean;
  onNote: (value: string) => void; onAccept: () => void; onReject: () => void;
}) {
  if (status !== "pending") return note ? <p className="review-note">审核说明：{note}</p> : null;
  return (
    <div className="review-actions">
      <label>审核说明<textarea value={note} onChange={(event) => onNote(event.target.value)} rows={2} placeholder="接受可选；拒绝必填" /></label>
      <div><button type="button" className="button reject" disabled={busy} onClick={onReject}>拒绝</button><button type="button" className="button primary" disabled={busy} onClick={onAccept}>{busy ? "处理中…" : "接受并写入核心数据"}</button></div>
    </div>
  );
}
