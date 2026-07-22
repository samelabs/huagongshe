"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/AccountContext";
import { EntityId } from "@/components/EntityId";
import type { ReactionDetail } from "@/lib/api";

type Role = "REACTANT" | "PRODUCT" | "REAGENT" | "CATALYST" | "SOLVENT";
type SourceType = "self" | "doi" | "patent" | "database" | "url" | "other";
type Participant = {
  key: number; role: Role; smiles: string; occurrence_count: string;
  amount_value: string; amount_unit: string; equivalents: string;
  concentration_value: string; concentration_unit: string; yield_percent: string;
};

const roleLabel: Record<Role, string> = {
  REACTANT: "反应物", PRODUCT: "产物", REAGENT: "试剂", CATALYST: "催化剂", SOLVENT: "溶剂",
};
let sequence = 1;
const blank = (role: Role, smiles = ""): Participant => ({
  key: sequence++, role, smiles, occurrence_count: "1", amount_value: "", amount_unit: "",
  equivalents: "", concentration_value: "", concentration_unit: "", yield_percent: "",
});

export function SubmissionForm() {
  const search = useSearchParams();
  const router = useRouter();
  const { user, ready } = useAccount();
  const reactionId = numberParam(search.get("reaction"));
  const chemicalId = numberParam(search.get("chemical"));
  const [details, setDetails] = useState<ReactionDetail | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([blank("REACTANT"), blank("PRODUCT")]);
  const [visibility, setVisibility] = useState<"public" | "private">("private");
  const [sourceType, setSourceType] = useState<SourceType>("self");
  const [editState, setEditState] = useState<"idle" | "loading" | "ready" | "error">(reactionId ? "loading" : "idle");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submitting = useRef(false);
  const idempotency = useRef({ key: "", body: "" });

  useEffect(() => {
    let active = true;
    if (reactionId) {
      setEditState("loading");
      setDetails(null);
      setParticipants([blank("REACTANT"), blank("PRODUCT")]);
      setVisibility("private");
      setMessage("");
      fetch(`/api/reactions/${reactionId}`, { cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error();
        const reaction = await response.json() as ReactionDetail;
        if (!reaction.is_owner) throw new Error();
        if (!active) return;
        setDetails(reaction);
        setVisibility(reaction.visibility);
        setSourceType((reaction.source_type || "self") as SourceType);
        setParticipants(reaction.participants.map((item) => ({
          key: sequence++, role: item.role as Role, smiles: item.smiles || "",
          occurrence_count: String(item.occurrence_count || 1),
          amount_value: item.amount_value == null ? "" : String(item.amount_value),
          amount_unit: item.amount_unit || "", equivalents: item.equivalents == null ? "" : String(item.equivalents),
          concentration_value: item.concentration_value == null ? "" : String(item.concentration_value),
          concentration_unit: item.concentration_unit || "",
          yield_percent: item.yield_percent == null ? "" : String(item.yield_percent),
        })));
        setEditState("ready");
      }).catch(() => {
        if (!active) return;
        setEditState("error");
        setMessage("该反应不存在、无权编辑，或暂时无法读取。请返回个人中心后重试。");
      });
      return () => { active = false; };
    }
    setDetails(null);
    setEditState("idle");
    setVisibility("private");
    setSourceType("self");
    setMessage("");
    if (chemicalId) {
      setParticipants([blank("REACTANT"), blank("PRODUCT")]);
      fetch(`/api/chemicals/${chemicalId}`, { cache: "no-store" }).then(async (response) => {
        if (!response.ok) return;
        const chemical = await response.json() as { smiles?: string };
        if (active && chemical.smiles) setParticipants([blank("REACTANT", chemical.smiles), blank("PRODUCT")]);
      });
      return () => { active = false; };
    }
    setParticipants([blank("REACTANT"), blank("PRODUCT")]);
    return () => { active = false; };
  }, [reactionId, chemicalId]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || (reactionId && editState !== "ready")) return;
    if (!user) { setMessage("请先登录。"); return; }
    const values = new FormData(event.currentTarget);
    const normalized = participants.filter((item) => item.smiles.trim()).map((item) => ({
      role: item.role, smiles: item.smiles.trim(), occurrence_count: Number(item.occurrence_count || 1),
      amount_value: numberOrNull(item.amount_value), amount_unit: textOrNull(item.amount_unit),
      equivalents: numberOrNull(item.equivalents),
      concentration_value: numberOrNull(item.concentration_value),
      concentration_unit: textOrNull(item.concentration_unit),
      yield_percent: item.role === "PRODUCT" ? numberOrNull(item.yield_percent) : null,
    }));
    const payload = {
      visibility: values.get("visibility"), participants: normalized,
      procedure_details: optional(values, "procedure_details"),
      conditions_detail: optional(values, "conditions_detail"),
      temperature_value: optionalNumber(values, "temperature_value"),
      temperature_unit: optional(values, "temperature_value") ? values.get("temperature_unit") : null,
      duration_value: optionalNumber(values, "duration_value"),
      duration_unit: optional(values, "duration_value") ? values.get("duration_unit") : null,
      ph: optionalNumber(values, "ph"), atmosphere: optional(values, "atmosphere"),
      pressure_value: optionalNumber(values, "pressure_value"),
      pressure_unit: optional(values, "pressure_value") ? optional(values, "pressure_unit") : null,
      workup_details: optional(values, "workup_details"), safety_notes: optional(values, "safety_notes"),
      source_type: values.get("source_type"), doi: optional(values, "doi"),
      patent: optional(values, "patent"), source_url: optional(values, "source_url"),
      source_citation: optional(values, "source_citation"), note: optional(values, "note"),
    };
    const validationError = validateDraft(normalized, values, sourceType);
    if (validationError) { setMessage(validationError); return; }

    submitting.current = true;
    setBusy(true);
    setMessage("");
    try {
      const serializedPayload = JSON.stringify(payload);
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (!reactionId) {
        if (idempotency.current.body !== serializedPayload) {
          idempotency.current = { key: crypto.randomUUID(), body: serializedPayload };
        }
        headers["Idempotency-Key"] = idempotency.current.key;
      }
      const response = await fetch(reactionId ? `/api/reactions/${reactionId}` : "/api/reactions", {
        method: reactionId ? "PUT" : "POST", headers, body: serializedPayload,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) { setMessage(apiError(body?.detail)); return; }
      router.push(`/reaction/${body.id}`);
      router.refresh();
    } catch {
      setMessage("网络连接失败，内容仍保留在本页，请稍后重试。");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const queryString = search.toString();
  const nextPath = `/submit${queryString ? `?${queryString}` : ""}`;
  if (!ready) return <p className="context-loading">正在读取账号…</p>;
  if (!user) return <div className="auth-required"><div><strong>请先登录</strong><span>登录后将反应保存到你的个人反应库。</span></div><Link href={`/login?next=${encodeURIComponent(nextPath)}`}>登录或注册</Link></div>;
  if (reactionId && editState === "loading") return <p className="context-loading">正在读取反应记录…</p>;
  if (reactionId && editState === "error") return <p className="form-message bad">{message}</p>;

  return (
    <form className="structured-form" onSubmit={submit} key={details?.updated_at || "new"} aria-busy={busy}>
      {reactionId && <div className="editing-context"><span>正在编辑</span><EntityId kind="reaction" id={reactionId} compact /></div>}
      <section className="form-section">
        <div className="form-section-head"><span>ACCESS</span><div><h2>可见性与来源</h2><p>私有记录仅自己可见；公开记录会显示在公开主页并可被他人查询和收藏。</p></div></div>
        <div className="form-fields two-columns">
          <label>可见性<select name="visibility" value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "private")}><option value="private">私有记录</option><option value="public">公开记录</option></select></label>
          <label>来源类型<select name="source_type" value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} disabled={busy}><option value="self">本人实验</option><option value="doi">文献 DOI</option><option value="patent">专利</option><option value="database">数据库</option><option value="url">网页</option><option value="other">其他</option></select></label>
          <label>DOI<input name="doi" defaultValue={details?.doi || ""} maxLength={300} required={sourceType === "doi"} disabled={busy} /></label>
          <label>专利号<input name="patent" defaultValue={details?.patent || ""} maxLength={300} required={sourceType === "patent"} disabled={busy} /></label>
          <label className="wide">来源链接<input name="source_url" type="url" defaultValue={details?.publication_url || ""} maxLength={1000} required={sourceType === "url"} disabled={busy} /></label>
          <label className="wide">来源说明<input name="source_citation" defaultValue={details?.source_citation || ""} placeholder="数据库记录、文章题目或其他可核对信息" maxLength={2000} required={sourceType === "database" || sourceType === "other"} disabled={busy} /></label>
        </div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><span>STRUCTURE</span><div><h2>参与物与角色</h2><p>系统按结构匹配 HCID；未匹配时创建新的 HCID。</p></div></div>
        <div className="participant-editor-cards">
          {participants.map((item) => <article className="participant-input-card" key={item.key}>
            <div className="participant-input-main">
              <select value={item.role} onChange={(event) => update(item.key, { role: event.target.value as Role })} disabled={busy}>{Object.entries(roleLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
              <input value={item.smiles} onChange={(event) => update(item.key, { smiles: event.target.value })} placeholder="SMILES" maxLength={4000} disabled={busy} />
              <button type="button" onClick={() => setParticipants((current) => current.filter((row) => row.key !== item.key))} disabled={busy || participants.length <= 2}>删除</button>
            </div>
            <div className="participant-measures">
              <label>次数<input type="number" min="1" max="20" value={item.occurrence_count} onChange={(event) => update(item.key, { occurrence_count: event.target.value })} /></label>
              <label>投料<input type="number" min="0" step="any" value={item.amount_value} onChange={(event) => update(item.key, { amount_value: event.target.value })} /></label>
              <label>单位<input value={item.amount_unit} onChange={(event) => update(item.key, { amount_unit: event.target.value })} placeholder="mmol" maxLength={40} /></label>
              <label>当量<input type="number" min="0" step="any" value={item.equivalents} onChange={(event) => update(item.key, { equivalents: event.target.value })} /></label>
              <label>浓度<input type="number" min="0" step="any" value={item.concentration_value} onChange={(event) => update(item.key, { concentration_value: event.target.value })} /></label>
              <label>浓度单位<input value={item.concentration_unit} onChange={(event) => update(item.key, { concentration_unit: event.target.value })} placeholder="mol/L" maxLength={40} /></label>
              {item.role === "PRODUCT" && <label>收率 %<input type="number" min="0" max="100" step="any" value={item.yield_percent} onChange={(event) => update(item.key, { yield_percent: event.target.value })} /></label>}
            </div>
          </article>)}
        </div>
        <div className="participant-add">{(Object.keys(roleLabel) as Role[]).map((role) => <button type="button" key={role} disabled={busy || participants.length >= 100} onClick={() => setParticipants((current) => [...current, blank(role)])}>+ {roleLabel[role]}</button>)}</div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><span>PROCESS</span><div><h2>过程与条件</h2><p>仅填写可确认的信息，其余字段留空。</p></div></div>
        <div className="form-fields">
          <label>实验过程<textarea name="procedure_details" rows={7} defaultValue={details?.procedure_details || ""} maxLength={30000} /></label>
          <div className="condition-fields">
            <label>温度<input name="temperature_value" type="number" step="any" defaultValue={details?.temperature?.value ?? ""} /></label><label>单位<select name="temperature_unit" defaultValue={details?.temperature?.unit || "CELSIUS"}><option value="CELSIUS">°C</option><option value="KELVIN">K</option></select></label>
            <label>时间<input name="duration_value" type="number" min="0.000001" step="any" defaultValue={details?.duration?.value ?? ""} /></label><label>单位<select name="duration_unit" defaultValue={details?.duration?.unit || "HOUR"}><option value="MINUTE">分钟</option><option value="HOUR">小时</option><option value="DAY">天</option></select></label>
            <label>pH<input name="ph" type="number" min="0" max="14" step="any" defaultValue={details?.ph ?? ""} /></label><label>气氛<input name="atmosphere" defaultValue={details?.atmosphere || ""} maxLength={120} /></label>
            <label>压力<input name="pressure_value" type="number" min="0.000001" step="any" defaultValue={details?.pressure?.value ?? ""} /></label><label>单位<input name="pressure_unit" defaultValue={details?.pressure?.unit || ""} placeholder="bar" maxLength={40} /></label>
          </div>
          <label>其他条件<textarea name="conditions_detail" rows={3} defaultValue={details?.conditions_detail || ""} maxLength={10000} /></label>
          <label>后处理<textarea name="workup_details" rows={3} defaultValue={details?.workup_details || ""} maxLength={10000} /></label>
          <label>安全说明<textarea name="safety_notes" rows={3} defaultValue={details?.safety_notes || ""} maxLength={10000} /></label>
          <label>补充说明<textarea name="note" rows={3} defaultValue={details?.note || ""} maxLength={10000} /></label>
        </div>
      </section>
      {message && <p className="form-message bad">{message}</p>}
      <button type="submit" className="button primary submit-button" disabled={busy}>{busy ? "校验并保存中…" : reactionId ? "保存修改" : visibility === "private" ? "保存为私有记录" : "公开并保存"}</button>
    </form>
  );

  function update(key: number, patch: Partial<Participant>) {
    setParticipants((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
  }
}

function numberParam(value: string | null) { return /^\d+$/.test(value || "") ? Number(value) : null; }
function textOrNull(value: string) { const result = value.trim(); return result || null; }
function numberOrNull(value: string) { return value.trim() === "" ? null : Number(value); }
function optional(values: FormData, key: string) { return textOrNull(String(values.get(key) || "")); }
function optionalNumber(values: FormData, key: string) { const value = optional(values, key); return value == null ? null : Number(value); }
function validateDraft(participants: Array<{ role: Role; amount_value: number | null; amount_unit: string | null; concentration_value: number | null; concentration_unit: string | null }>, values: FormData, sourceType: SourceType) {
  if (!participants.some((item) => item.role === "REACTANT") || !participants.some((item) => item.role === "PRODUCT")) return "至少需要填写一个反应物和一个产物。";
  if (participants.some((item) => (item.amount_value == null) !== (item.amount_unit == null))) return "每个参与物的投料数值和单位必须同时填写。";
  if (participants.some((item) => (item.concentration_value == null) !== (item.concentration_unit == null))) return "每个参与物的浓度数值和单位必须同时填写。";
  const requiredSource: Partial<Record<SourceType, string>> = { doi: "doi", patent: "patent", database: "source_citation", url: "source_url", other: "source_citation" };
  const sourceField = requiredSource[sourceType];
  if (sourceField && !optional(values, sourceField)) return "请填写与来源类型对应的来源信息。";
  return "";
}
function apiError(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg).filter(Boolean).join("；") || "校验失败";
  return "保存失败，请稍后重试";
}
