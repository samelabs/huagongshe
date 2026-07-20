"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { EntityId } from "@/components/EntityId";
import { Molecule } from "@/components/Molecule";

type Kind = "chemical" | "reaction";
type User = { id: number; username: string; role: string };
type Status = "pending" | "accepted" | "rejected";
type Submission = {
  id: number; status: Status; chemical_id?: number | null; reaction_id?: number | null;
  submitted_name?: string | null; submitted_smiles?: string | null;
  reaction_smiles?: string | null; review_note?: string | null; created_at: string;
};
type SubmissionHistory = { chemicals: Submission[]; reactions: Submission[] };
type Participant = { key: number; role: Role; smiles: string; yield_percent: string };
type Role = "REACTANT" | "PRODUCT" | "REAGENT" | "CATALYST" | "SOLVENT";

const statusLabel: Record<Status, string> = { pending: "待审核", accepted: "已接受", rejected: "已拒绝" };
const roleLabel: Record<Role, string> = { REACTANT: "反应物", PRODUCT: "生成物", REAGENT: "试剂", CATALYST: "催化剂", SOLVENT: "溶剂" };
let rowSequence = 10;
const blankRow = (role: Role): Participant => ({ key: rowSequence++, role, smiles: "", yield_percent: "" });

export function SubmissionForm() {
  const search = useSearchParams();
  const initial = search.get("type") === "reaction" ? "reaction" : "chemical";
  const reactionId = numberParam(search.get("reaction"));
  const chemicalId = numberParam(search.get("chemical"));
  const [kind, setKind] = useState<Kind>(initial);
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [history, setHistory] = useState<SubmissionHistory | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [contextBusy, setContextBusy] = useState(Boolean(reactionId || chemicalId));
  const [participants, setParticipants] = useState<Participant[]>([blankRow("REACTANT"), blankRow("PRODUCT")]);
  const [chemicalDraft, setChemicalDraft] = useState({ smiles: "", cas: "", name: "" });

  async function loadHistory() {
    const response = await fetch("/api/community/my-submissions", { cache: "no-store" });
    if (response.ok) setHistory(await response.json());
  }

  useEffect(() => {
    fetch("/api/community/me", { cache: "no-store" }).then(async (response) => {
      if (response.ok) {
        setUser(await response.json());
        await loadHistory();
      }
      setAuthReady(true);
    }).catch(() => setAuthReady(true));
  }, []);

  useEffect(() => {
    if (reactionId) {
      fetch(`/api/reactions/${reactionId}`, { cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error();
        const data = await response.json() as { participants: { role: Role; smiles: string; yield_percent?: number | null }[] };
        setParticipants(data.participants.filter((item) => roleLabel[item.role]).map((item) => ({
          key: rowSequence++, role: item.role, smiles: item.smiles || "",
          yield_percent: item.yield_percent == null ? "" : String(item.yield_percent),
        })));
      }).catch(() => setMessage({ ok: false, text: `HRID ${reactionId} 无法读取，未进行预填。` })).finally(() => setContextBusy(false));
      return;
    }
    if (chemicalId) {
      fetch(`/api/chemicals/${chemicalId}`, { cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error();
        const data = await response.json() as { smiles: string | null; cas_numbers: string[]; preferred_name: string | null };
        if (initial === "chemical") setChemicalDraft({ smiles: data.smiles || "", cas: data.cas_numbers[0] || "", name: data.preferred_name || "" });
        else if (data.smiles) setParticipants([ { key: rowSequence++, role: "REACTANT", smiles: data.smiles, yield_percent: "" }, blankRow("PRODUCT") ]);
      }).catch(() => setMessage({ ok: false, text: `HCID ${chemicalId} 无法读取，未进行预填。` })).finally(() => setContextBusy(false));
      return;
    }
    setContextBusy(false);
  }, [reactionId, chemicalId, initial]);

  const groupedCounts = useMemo(() => participants.reduce<Record<string, number>>((result, item) => {
    result[item.role] = (result[item.role] || 0) + 1; return result;
  }, {}), [participants]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) { setMessage({ ok: false, text: "请先登录后提交。" }); return; }
    setBusy(true); setMessage(null);
    const form = event.currentTarget;
    const values = new FormData(form);
    let payload: Record<string, unknown>;
    if (kind === "chemical") {
      payload = { ...chemicalDraft, note: values.get("note") || null };
    } else {
      const normalized = participants.filter((item) => item.smiles.trim()).map((item) => ({
        role: item.role, smiles: item.smiles.trim(),
        yield_percent: item.role === "PRODUCT" && item.yield_percent !== "" ? Number(item.yield_percent) : null,
      }));
      if (!normalized.some((item) => item.role === "REACTANT") || !normalized.some((item) => item.role === "PRODUCT")) {
        setMessage({ ok: false, text: "至少填写一个反应物和一个生成物。" }); setBusy(false); return;
      }
      payload = {
        reaction_id: reactionId, participants: normalized,
        procedure_details: values.get("procedure_details"), conditions_detail: optional(values, "conditions_detail"),
        temperature_value: optionalNumber(values, "temperature_value"),
        temperature_unit: optional(values, "temperature_value") ? values.get("temperature_unit") : null,
        duration_value: optionalNumber(values, "duration_value"),
        duration_unit: optional(values, "duration_value") ? values.get("duration_unit") : null,
        ph: optionalNumber(values, "ph"), atmosphere: optional(values, "atmosphere"),
        pressure_value: optionalNumber(values, "pressure_value"),
        pressure_unit: optional(values, "pressure_value") ? optional(values, "pressure_unit") : null,
        safety_notes: optional(values, "safety_notes"), doi: optional(values, "doi"),
        patent: optional(values, "patent"), source_url: optional(values, "source_url"), note: optional(values, "note"),
      };
    }
    const response = await fetch(`/api/community/${kind}-submissions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (response.status === 401) { setUser(null); setMessage({ ok: false, text: "登录已过期，请重新登录。" }); setBusy(false); return; }
    const body = await response.json().catch(() => null);
    if (!response.ok) { setMessage({ ok: false, text: apiError(body?.detail) }); setBusy(false); return; }
    setMessage({ ok: true, text: `提交 ${body.id} 已通过结构校验，进入人工审核。` });
    if (!reactionId && kind === "reaction") setParticipants([blankRow("REACTANT"), blankRow("PRODUCT")]);
    if (!chemicalId && kind === "chemical") setChemicalDraft({ smiles: "", cas: "", name: "" });
    form.reset(); await loadHistory(); setBusy(false);
  }

  return (
    <>
      {authReady && !user && <div className="auth-required"><div><strong>提交需要账号</strong><span>用于追踪审核结果与避免重复写入。</span></div><Link href="/login">登录或注册</Link></div>}
      <div className="submission-tabs" role="tablist">
        <button type="button" className={kind === "chemical" ? "active" : ""} onClick={() => { setKind("chemical"); setMessage(null); }}><span>01</span> 化合物</button>
        <button type="button" className={kind === "reaction" ? "active" : ""} onClick={() => { setKind("reaction"); setMessage(null); }}><span>02</span> 反应</button>
      </div>
      {contextBusy ? <p className="context-loading">正在读取关联数据…</p> : (
        <form className="structured-form" onSubmit={submit}>
          {kind === "chemical" ? (
            <section className="form-section">
                <div className="form-section-head"><span>IDENTITY</span><div><h2>{chemicalId ? <>确认 <EntityId kind="chemical" id={chemicalId} compact /> 身份</> : "确认化合物身份"}</h2><p>SMILES 决定结构，CAS 与名称作为待审核身份信息；两者冲突时系统会拒绝提交。</p></div></div>
              {chemicalDraft.smiles && <div className="submission-preview"><Molecule smiles={chemicalDraft.smiles} width={220} height={150} /><span>结构预览</span></div>}
              <div className="form-fields two-columns">
                <label className="wide">SMILES <input value={chemicalDraft.smiles} onChange={(event) => setChemicalDraft((current) => ({ ...current, smiles: event.target.value }))} placeholder="例如 CCO" /></label>
                <label>CAS <input value={chemicalDraft.cas} onChange={(event) => setChemicalDraft((current) => ({ ...current, cas: event.target.value }))} placeholder="例如 64-17-5" /></label>
                <label>推荐名称 <input value={chemicalDraft.name} onChange={(event) => setChemicalDraft((current) => ({ ...current, name: event.target.value }))} /></label>
              </div>
              <p className="field-help">至少填写 SMILES 或 CAS。若同时填写，必须能够指向同一结构。</p>
            </section>
          ) : (
            <>
              <section className="form-section">
                <div className="form-section-head"><span>STRUCTURE</span><div><h2>{reactionId ? <><span className="heading-action">修订</span> <EntityId kind="reaction" id={reactionId} compact /></> : "定义参与物与角色"}</h2><p>逐项填写参与物、生成物与其他组分，避免角色混淆。</p></div></div>
                <div className="participant-editor">
                  <div className="participant-editor-labels"><span>角色</span><span>SMILES</span><span>收率</span><span /></div>
                  {participants.map((item) => (
                    <div className="participant-row" key={item.key}>
                      <select value={item.role} onChange={(event) => updateParticipant(item.key, { role: event.target.value as Role })}>{Object.entries(roleLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
                      <input value={item.smiles} onChange={(event) => updateParticipant(item.key, { smiles: event.target.value })} placeholder="SMILES" aria-label={`${roleLabel[item.role]} SMILES`} />
                      {item.role === "PRODUCT" ? <input value={item.yield_percent} onChange={(event) => updateParticipant(item.key, { yield_percent: event.target.value })} type="number" min="0" max="100" step="any" placeholder="%" aria-label="产物收率" /> : <span className="not-applicable">—</span>}
                      <button type="button" onClick={() => setParticipants((current) => current.filter((row) => row.key !== item.key))} disabled={participants.length <= 2} aria-label="删除参与物">×</button>
                    </div>
                  ))}
                </div>
                <div className="participant-add">{(["REACTANT", "PRODUCT", "REAGENT", "CATALYST", "SOLVENT"] as Role[]).map((role) => <button type="button" key={role} onClick={() => setParticipants((current) => [...current, blankRow(role)])}>+ {roleLabel[role]}{groupedCounts[role] ? ` ${groupedCounts[role]}` : ""}</button>)}</div>
              </section>

              <section className="form-section">
                <div className="form-section-head"><span>PROCEDURE</span><div><h2>过程与条件</h2><p>过程是可复现事实；标准条件单独填写，其他条件保留原始叙述。</p></div></div>
                <div className="form-fields">
                  <label>实验过程 <textarea name="procedure_details" required minLength={10} rows={7} placeholder="按操作顺序记录投料、温度变化、反应、后处理和纯化" /></label>
                  <div className="condition-fields">
                    <label>温度 <input name="temperature_value" type="number" step="any" /></label>
                    <label>单位 <select name="temperature_unit" defaultValue="CELSIUS"><option value="CELSIUS">°C</option><option value="KELVIN">K</option></select></label>
                    <label>时间 <input name="duration_value" type="number" min="0" step="any" /></label>
                    <label>单位 <select name="duration_unit" defaultValue="HOUR"><option value="MINUTE">分钟</option><option value="HOUR">小时</option><option value="DAY">天</option></select></label>
                    <label>pH <input name="ph" type="number" min="0" max="14" step="any" /></label>
                    <label>气氛 <input name="atmosphere" placeholder="N₂" /></label>
                    <label>压力 <input name="pressure_value" type="number" min="0" step="any" /></label>
                    <label>单位 <input name="pressure_unit" placeholder="bar" /></label>
                  </div>
                  <label>其他条件 <textarea name="conditions_detail" rows={3} placeholder="光照、搅拌、电化学等" /></label>
                  <label>安全说明 <textarea name="safety_notes" rows={3} /></label>
                </div>
              </section>

              <section className="form-section">
                <div className="form-section-head"><span>EVIDENCE</span><div><h2>来源依据</h2><p>来源用于复核，不作为页面标题。</p></div></div>
                <div className="form-fields two-columns">
                  <label>DOI <input name="doi" placeholder="10.xxxx/…" /></label>
                  <label>专利号 <input name="patent" /></label>
                  <label className="wide">来源链接 <input name="source_url" type="url" placeholder="https://…" /></label>
                </div>
              </section>
            </>
          )}
          <section className="form-section final-section">
            <label>提交说明 <textarea name="note" rows={3} placeholder="说明新增、补充或修订的依据（可选）" /></label>
            {message && <p className={`form-message ${message.ok ? "ok" : "bad"}`}>{message.text}</p>}
            <button className="button primary submit-button" disabled={busy || !user}>{busy ? "校验中…" : "校验并提交审核"}</button>
          </section>
        </form>
      )}
      {history && <SubmissionHistoryView history={history} />}
    </>
  );

  function updateParticipant(key: number, patch: Partial<Participant>) {
    setParticipants((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
  }
}

function SubmissionHistoryView({ history }: { history: SubmissionHistory }) {
  const items = [
    ...history.chemicals.map((item) => ({ ...item, kind: "化合物" })),
    ...history.reactions.map((item) => ({ ...item, kind: "反应" })),
  ].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 20);
  if (!items.length) return null;
  return <section className="submission-history"><div className="section-heading compact-heading"><div><p>HISTORY</p><h2>我的提交</h2></div></div><div>{items.map((item) => (
    <article key={`${item.kind}-${item.id}`}><div><strong>{item.kind}提交 {item.id}</strong><span className={`status ${item.status}`}>{statusLabel[item.status]}</span></div><p>{item.submitted_name || item.submitted_smiles || item.reaction_smiles || "结构化数据"}</p>{item.review_note && <small>审核说明：{item.review_note}</small>}{item.status === "accepted" && item.chemical_id && <Link href={`/chemical/${item.chemical_id}`}><EntityId kind="chemical" id={item.chemical_id} compact /></Link>}{item.status === "accepted" && item.reaction_id && <Link href={`/reaction/${item.reaction_id}`}><EntityId kind="reaction" id={item.reaction_id} compact /></Link>}</article>
  ))}</div></section>;
}

function numberParam(value: string | null) { return /^\d+$/.test(value || "") ? Number(value) : null; }
function optional(values: FormData, key: string) { const value = String(values.get(key) || "").trim(); return value || null; }
function optionalNumber(values: FormData, key: string) { const value = optional(values, key); return value == null ? null : Number(value); }
function apiError(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg).filter(Boolean).join("；") || "校验失败";
  return "校验失败";
}
