"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Molecule } from "@/components/Molecule";

type Status = "pending" | "accepted" | "rejected";
type ChemicalSubmission = {
  id: number; username: string; chemical_id: number | null; submitted_smiles: string | null;
  submitted_cas: string | null; submitted_name: string | null; note: string | null;
  status: Status; review_note: string | null; created_at: string;
};
type Participant = { position: number; role: string; submitted_smiles: string; canonical_smiles: string; chemical_id: number | null; yield_percent: number | null };
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

const roleName: Record<string, string> = { REACTANT: "反应物", PRODUCT: "生成物", REAGENT: "试剂", CATALYST: "催化剂", SOLVENT: "溶剂" };
const statusName: Record<Status, string> = { pending: "待审核", accepted: "已接受", rejected: "已拒绝" };

export function AdminReview() {
  const [status, setStatus] = useState<Status>("pending");
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setError(""); setQueue(null);
    const response = await fetch(`/api/community/admin/submissions?status=${status}`, { cache: "no-store" });
    if (!response.ok) {
      setError(response.status === 403 ? "当前账号没有审核权限。" : response.status === 401 ? "请先登录审核账号。" : "审核队列读取失败。"); return;
    }
    setQueue(await response.json());
  }, [status]);

  useEffect(() => { load(); }, [load]);

  async function review(kind: "chemical" | "reaction", id: number, decision: "accept" | "reject") {
    const key = `${kind}-${id}`;
    const reviewNote = (notes[key] || "").trim();
    if (decision === "reject" && !reviewNote) { setError("拒绝提交必须填写审核说明。"); return; }
    const warning = kind === "reaction"
      ? "确认参与物、角色、方程式、条件与来源均已核对？接受后会写入 reactions 及其 chemical 关系。"
      : "确认结构与身份信息一致，并且来源足以支持写入 chemicals？";
    if (decision === "accept" && !window.confirm(warning)) return;
    setBusy(key); setError("");
    const response = await fetch(`/api/community/admin/${kind}-submissions/${id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, review_note: reviewNote || null }),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) { setError(typeof body?.detail === "string" ? body.detail : "审核操作失败。"); setBusy(""); return; }
    setBusy(""); await load();
  }

  return (
    <>
      <div className="review-status-tabs">{(["pending", "accepted", "rejected"] as Status[]).map((value) => (
        <button type="button" key={value} className={status === value ? "active" : ""} onClick={() => setStatus(value)}>{statusName[value]}</button>
      ))}</div>
      {error && <div className="notice error">{error}</div>}
      {!queue && !error && <p className="context-loading">正在读取审核队列…</p>}
      {queue && queue.chemicals.length === 0 && queue.reactions.length === 0 && <div className="empty-state"><strong>当前队列为空</strong><p>没有符合该状态的提交。</p></div>}
      {queue && queue.chemicals.length > 0 && <section className="review-section"><div className="section-heading"><div><p>CHEMICALS</p><h2>化合物身份</h2></div><span>{queue.chemicals.length} 条</span></div>{queue.chemicals.map((item) => {
        const key = `chemical-${item.id}`;
        return <article className="review-item chemical-review" key={key}>
          <header><div><p>提交 {item.id} · {formatDate(item.created_at)}</p><h3>{item.submitted_name || "未命名化合物"}</h3><span>提交人 {item.username}</span></div>{item.chemical_id && <Link href={`/chemical/${item.chemical_id}`}>查看匹配化合物 {item.chemical_id}</Link>}</header>
          <div className="chemical-review-body">
            <div className="review-molecule"><Molecule smiles={item.submitted_smiles} width={260} height={180} /></div>
            <dl><Data label="SMILES" value={item.submitted_smiles} mono /><Data label="CAS" value={item.submitted_cas} /><Data label="名称" value={item.submitted_name} /><Data label="提交说明" value={item.note} /></dl>
          </div>
          {!item.submitted_smiles && <div className="review-warning">该提交只有 CAS，若未唯一匹配现有 chemicals，不应接受。</div>}
          <ReviewActions status={item.status} note={notes[key] ?? item.review_note ?? ""} busy={busy === key} onNote={(value) => setNotes((current) => ({ ...current, [key]: value }))} onAccept={() => review("chemical", item.id, "accept")} onReject={() => review("chemical", item.id, "reject")} />
        </article>;
      })}</section>}
      {queue && queue.reactions.length > 0 && <section className="review-section"><div className="section-heading"><div><p>REACTIONS</p><h2>反应事实</h2></div><span>{queue.reactions.length} 条</span></div>{queue.reactions.map((item) => {
        const key = `reaction-${item.id}`;
        return <article className="review-item reaction-review" key={key}>
          <header><div><p>提交 {item.id} · {formatDate(item.created_at)}</p><h3>{item.reaction_id ? `修订反应 ${item.reaction_id}` : "新增反应"}</h3><span>提交人 {item.username}</span></div>{item.reaction_id && <Link href={`/reaction/${item.reaction_id}`}>打开当前反应</Link>}</header>
          {item.reaction_id && <div className="comparison-labels"><span>提交版本</span><span>当前版本需另页核对</span></div>}
          <div className="review-reaction-scheme">{/* eslint-disable-next-line @next/next/no-img-element */}<img src={`/api/community/admin/reaction-submissions/${item.id}/svg?w=1400&h=300`} width="1400" height="300" alt={`反应提交 ${item.id} 方程式`} /></div>
          <div className="review-participant-table">{item.participants.map((participant) => <div key={participant.position}><span>{roleName[participant.role] || participant.role}</span><code>{participant.canonical_smiles}</code>{participant.yield_percent != null ? <strong>{participant.yield_percent}%</strong> : <i>—</i>}</div>)}</div>
          <dl className="review-data"><Data label="实验过程" value={item.procedure_details} /><Data label="其他条件" value={item.conditions_detail} /><Data label="标准条件" value={conditionLine(item)} /><Data label="来源" value={[item.doi, item.patent, item.source_url].filter(Boolean).join(" · ")} /><Data label="安全说明" value={item.safety_notes} /><Data label="提交说明" value={item.note} /></dl>
          <details className="source-expression"><summary>检查 RDKit 反应表达</summary><p className="mono">{item.reaction_smiles}</p></details>
          <ReviewActions status={item.status} note={notes[key] ?? item.review_note ?? ""} busy={busy === key} onNote={(value) => setNotes((current) => ({ ...current, [key]: value }))} onAccept={() => review("reaction", item.id, "accept")} onReject={() => review("reaction", item.id, "reject")} />
        </article>;
      })}</section>}
    </>
  );
}

function ReviewActions({ status, note, busy, onNote, onAccept, onReject }: { status: Status; note: string; busy: boolean; onNote: (value: string) => void; onAccept: () => void; onReject: () => void }) {
  if (status !== "pending") return note ? <p className="review-decision">审核说明：{note}</p> : null;
  return <div className="review-actions"><label>审核说明<textarea value={note} onChange={(event) => onNote(event.target.value)} rows={3} placeholder="记录接受依据；拒绝时必须说明原因" /></label><div><button type="button" className="button danger" disabled={busy} onClick={onReject}>拒绝</button><button type="button" className="button primary" disabled={busy} onClick={onAccept}>{busy ? "写入中…" : "核对无误，接受"}</button></div></div>;
}

function Data({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd className={mono ? "mono" : ""}>{value}</dd></div>;
}

function conditionLine(item: ReactionSubmission) {
  return [item.temperature_value != null ? `${item.temperature_value} ${item.temperature_unit}` : null, item.duration_value != null ? `${item.duration_value} ${item.duration_unit}` : null, item.ph != null ? `pH ${item.ph}` : null, item.atmosphere, item.pressure_value != null ? `${item.pressure_value} ${item.pressure_unit}` : null].filter(Boolean).join(" · ");
}

function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value)); }
