"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

type Kind = "chemical" | "reaction";
type User = { id: number; username: string; role: string };
type Submission = {
  id: number; status: "pending" | "accepted" | "rejected";
  chemical_id?: number | null; reaction_id?: number | null;
  submitted_name?: string | null; submitted_smiles?: string | null;
  reaction_smiles?: string | null; review_note?: string | null; created_at: string;
};
type SubmissionHistory = { chemicals: Submission[]; reactions: Submission[] };
type Participant = { role: string; smiles: string; yield_percent?: number };

const statusLabel = { pending: "待审核", accepted: "已接受", rejected: "已拒绝" };

function apiError(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg).filter(Boolean).join("；") || "校验失败";
  return "校验失败";
}

function parseLines(raw: FormDataEntryValue | null, role: string, products = false): Participant[] {
  return String(raw || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    if (!products) return { role, smiles: line };
    const [smiles, rawYield, ...rest] = line.split("|").map((value) => value.trim());
    if (rest.length || !smiles) throw new Error("产物格式应为：SMILES | 收率")
    if (!rawYield) return { role, smiles };
    const yieldPercent = Number(rawYield.replace(/%$/, ""));
    if (!Number.isFinite(yieldPercent) || yieldPercent < 0 || yieldPercent > 100) {
      throw new Error(`产物收率无效：${rawYield}`);
    }
    return { role, smiles, yield_percent: yieldPercent };
  });
}

function optionalNumber(value: FormDataEntryValue | null) {
  const text = String(value || "").trim();
  return text ? Number(text) : null;
}

export function SubmissionForm() {
  const search = useSearchParams();
  const initial = search.get("type") === "reaction" ? "reaction" : "chemical";
  const reactionId = /^\d+$/.test(search.get("reaction") || "") ? Number(search.get("reaction")) : null;
  const [kind, setKind] = useState<Kind>(initial);
  const [user, setUser] = useState<User | null>(null);
  const [history, setHistory] = useState<SubmissionHistory | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadHistory() {
    const response = await fetch("/api/community/my-submissions", { cache: "no-store" });
    if (response.ok) setHistory(await response.json());
  }

  useEffect(() => {
    fetch("/api/community/me", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) return;
      setUser(await response.json());
      await loadHistory();
    }).catch(() => undefined);
  }, []);

  return (
    <>
      {!user && (
        <div className="auth-required">提交需要登录，审核结果会保留在账号中。<Link href="/login">登录或注册</Link></div>
      )}
      <div className="tabs">
        <button type="button" className={kind === "chemical" ? "active" : ""} onClick={() => { setKind("chemical"); setMessage(null); }}>化合物</button>
        <button type="button" className={kind === "reaction" ? "active" : ""} onClick={() => { setKind("reaction"); setMessage(null); }}>反应</button>
      </div>
      <form className="form-stack submission-form" onSubmit={async (event) => {
        event.preventDefault();
        if (!user) { setMessage({ ok: false, text: "请先登录后提交" }); return; }
        const form = event.currentTarget;
        const values = new FormData(form);
        setBusy(true); setMessage(null);
        let payload: Record<string, unknown>;
        try {
          if (kind === "chemical") {
            payload = {
              smiles: values.get("smiles") || null, cas: values.get("cas") || null,
              name: values.get("name") || null, note: values.get("note") || null,
            };
          } else {
            const participants = [
              ...parseLines(values.get("reactants"), "REACTANT"),
              ...parseLines(values.get("products"), "PRODUCT", true),
              ...parseLines(values.get("reagents"), "REAGENT"),
              ...parseLines(values.get("catalysts"), "CATALYST"),
              ...parseLines(values.get("solvents"), "SOLVENT"),
            ];
            payload = {
              reaction_id: reactionId, participants,
              procedure_details: values.get("procedure_details"),
              conditions_detail: values.get("conditions_detail") || null,
              temperature_value: optionalNumber(values.get("temperature_value")),
              temperature_unit: values.get("temperature_value") ? values.get("temperature_unit") : null,
              duration_value: optionalNumber(values.get("duration_value")),
              duration_unit: values.get("duration_value") ? values.get("duration_unit") : null,
              ph: optionalNumber(values.get("ph")), atmosphere: values.get("atmosphere") || null,
              pressure_value: optionalNumber(values.get("pressure_value")),
              pressure_unit: values.get("pressure_value") ? values.get("pressure_unit") : null,
              safety_notes: values.get("safety_notes") || null,
              doi: values.get("doi") || null, patent: values.get("patent") || null,
              source_url: values.get("source_url") || null, note: values.get("note") || null,
            };
          }
        } catch (error) {
          setMessage({ ok: false, text: error instanceof Error ? error.message : "表单格式不正确" });
          setBusy(false); return;
        }
        const response = await fetch(`/api/community/${kind}-submissions`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        if (response.status === 401) { setUser(null); setMessage({ ok: false, text: "登录已过期，请重新登录" }); setBusy(false); return; }
        const body = await response.json().catch(() => null);
        if (!response.ok) { setMessage({ ok: false, text: apiError(body?.detail) }); setBusy(false); return; }
        setMessage({ ok: true, text: `提交 #${body.id} 已完成结构校验，正在等待人工审核。` });
        form.reset(); await loadHistory(); setBusy(false);
      }}>
        {kind === "chemical" ? (
          <fieldset>
            <legend>化合物身份</legend>
            <label>标准结构（SMILES）<input name="smiles" placeholder="例如 CCO" /></label>
            <div className="form-grid two">
              <label>CAS<input name="cas" placeholder="例如 64-17-5" /></label>
              <label>名称<input name="name" placeholder="推荐名称（可选）" /></label>
            </div>
            <p className="field-hint">至少填写 SMILES 或 CAS。系统只负责校验和匹配，人工审核后才写入核心数据。</p>
          </fieldset>
        ) : (
          <>
            <fieldset>
              <legend>参与物与角色</legend>
              {reactionId && <p className="target-note">补充或纠正反应 #{reactionId}</p>}
              <div className="form-grid two">
                <label>反应物（每行一个 SMILES）<textarea name="reactants" required rows={5} placeholder={"CCO\nCC(=O)O"} /></label>
                <label>产物（SMILES | 收率%）<textarea name="products" required rows={5} placeholder={"CCOC(C)=O | 82"} /></label>
                <label>试剂<textarea name="reagents" rows={3} placeholder="每行一个 SMILES（可选）" /></label>
                <label>催化剂<textarea name="catalysts" rows={3} placeholder="每行一个 SMILES（可选）" /></label>
                <label>溶剂<textarea name="solvents" rows={3} placeholder="每行一个 SMILES（可选）" /></label>
              </div>
              <p className="field-hint">角色分别进入 REACTANT、PRODUCT、REAGENT、CATALYST、SOLVENT，不再依赖一条混合文本猜测。</p>
            </fieldset>
            <fieldset>
              <legend>过程与条件</legend>
              <label>实验过程<textarea name="procedure_details" required minLength={10} rows={6} placeholder="按操作顺序记录投料、温度变化、反应、后处理和纯化过程" /></label>
              <div className="form-grid condition-grid">
                <label>温度<input name="temperature_value" type="number" step="any" /></label>
                <label>单位<select name="temperature_unit" defaultValue="CELSIUS"><option value="CELSIUS">°C</option><option value="KELVIN">K</option></select></label>
                <label>时间<input name="duration_value" type="number" min="0" step="any" /></label>
                <label>单位<select name="duration_unit" defaultValue="HOUR"><option value="MINUTE">分钟</option><option value="HOUR">小时</option><option value="DAY">天</option></select></label>
                <label>pH<input name="ph" type="number" min="0" max="14" step="any" /></label>
                <label>气氛<input name="atmosphere" placeholder="例如 N₂" /></label>
                <label>压力<input name="pressure_value" type="number" min="0" step="any" /></label>
                <label>压力单位<input name="pressure_unit" placeholder="例如 bar" /></label>
              </div>
              <label>其他条件<textarea name="conditions_detail" rows={3} placeholder="搅拌、光照、电化学等无法放入标准字段的条件" /></label>
              <label>安全说明<textarea name="safety_notes" rows={3} placeholder="危险、放热、惰性操作或处置要求（可选）" /></label>
            </fieldset>
            <fieldset>
              <legend>来源</legend>
              <div className="form-grid two">
                <label>DOI<input name="doi" placeholder="10.xxxx/…" /></label>
                <label>专利号<input name="patent" /></label>
              </div>
              <label>来源链接<input name="source_url" type="url" placeholder="https://…" /></label>
            </fieldset>
          </>
        )}
        <label>提交说明（可选）<textarea name="note" rows={3} placeholder="说明新增、补充或纠正的依据" /></label>
        {message && <p className={`form-message ${message.ok ? "ok" : "bad"}`}>{message.text}</p>}
        <button className="button primary" disabled={busy || !user}>{busy ? "校验中…" : "校验并提交审核"}</button>
      </form>
      {history && (history.chemicals.length > 0 || history.reactions.length > 0) && (
        <section className="submission-history">
          <h2>我的提交</h2>
          {[...history.chemicals.map((item) => ({ ...item, kind: "化合物" })), ...history.reactions.map((item) => ({ ...item, kind: "反应" }))]
            .sort((a, b) => b.id - a.id).slice(0, 20).map((item) => (
              <article key={`${item.kind}-${item.id}`}>
                <div><strong>{item.kind} #{item.id}</strong><span className={`status ${item.status}`}>{statusLabel[item.status]}</span></div>
                <p>{item.submitted_name || item.submitted_smiles || item.reaction_smiles || "结构化提交"}</p>
                {item.review_note && <small>审核说明：{item.review_note}</small>}
                {item.status === "accepted" && item.chemical_id && <Link href={`/chemical/${item.chemical_id}`}>查看化合物</Link>}
                {item.status === "accepted" && item.reaction_id && <Link href={`/reaction/${item.reaction_id}`}>查看反应</Link>}
              </article>
            ))}
        </section>
      )}
    </>
  );
}
