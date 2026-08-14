"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet, apiPost, apiPut, ApiError, type ReactionDetail } from "@/lib/api";
import t from "@/lib/i18n";

type Role = "REACTANT" | "PRODUCT" | "REAGENT" | "CATALYST" | "SOLVENT";
type SourceType = "self" | "doi" | "patent" | "database" | "url" | "other";
type Participant = {
  key: number; role: Role; smiles: string; occurrence_count: string;
  amount_value: string; amount_unit: string; equivalents: string;
  concentration_value: string; concentration_unit: string; yield_percent: string;
};

const roleLabel: Record<Role, string> = {
  REACTANT: t.submit.roles.reactant, PRODUCT: t.submit.roles.product, REAGENT: t.submit.roles.reagent, CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
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
      apiGet<ReactionDetail>(`/reactions/${reactionId}`).then((reaction) => {
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
        setMessage(t.submit.errNotFound);
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
      apiGet<{ smiles?: string }>(`/chemicals/${chemicalId}`).then((chemical) => {
        if (active && chemical.smiles) setParticipants([blank("REACTANT", chemical.smiles), blank("PRODUCT")]);
      }).catch(() => {});
      return () => { active = false; };
    }
    setParticipants([blank("REACTANT"), blank("PRODUCT")]);
    return () => { active = false; };
  }, [reactionId, chemicalId]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || (reactionId && editState !== "ready")) return;
    if (!user) { setMessage(t.submit.errNotLogin); return; }
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
      const headers: Record<string, string> = {};
      if (!reactionId) {
        if (idempotency.current.body !== serializedPayload) {
          idempotency.current = { key: crypto.randomUUID(), body: serializedPayload };
        }
        headers["Idempotency-Key"] = idempotency.current.key;
      }
      const body = reactionId
        ? await apiPut<{ id: number }>(`/reactions/${reactionId}`, serializedPayload, headers)
        : await apiPost<{ id: number }>("/reactions", serializedPayload, headers);
      router.push(`/reaction/${body.id}`);
      router.refresh();
    } catch (err) {
      setMessage(err instanceof ApiError ? t.submit.errSave : t.submit.errNetwork);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const queryString = search.toString();
  const nextPath = `/submit${queryString ? `?${queryString}` : ""}`;
  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <div className="auth-required"><div><strong>{t.submit.loginRequired}</strong><span>{t.submit.loginHint}</span></div><Link href={`/login?next=${encodeURIComponent(nextPath)}`}>{t.common.loginOrRegister}</Link></div>;
  if (reactionId && editState === "loading") return <p className="context-loading">{t.submit.readingRecord}</p>;
  if (reactionId && editState === "error") return <p className="form-message bad">{message}</p>;

  return (
    <form className="structured-form" onSubmit={submit} key={details?.updated_at || "new"} aria-busy={busy}>
      {reactionId && <div className="editing-context"><span>{t.submit.editing}</span><EntityId kind="reaction" id={reactionId} compact /></div>}
      <section className="form-section">
        <div className="form-section-head"><span>ACCESS</span><div><h2>{t.submit.visibilitySource}</h2><p>{t.submit.visibilityHint}</p></div></div>
        <div className="form-fields two-columns">
          <label>{t.submit.visibility}<select name="visibility" value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "private")}><option value="private">{t.submit.privateRecord}</option><option value="public">{t.submit.publicRecord}</option></select></label>
          <label>{t.submit.sourceType}<select name="source_type" value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} disabled={busy}><option value="self">{t.reaction.sourceTypes.personal}</option><option value="doi">{t.reaction.sourceTypes.literature} DOI</option><option value="patent">{t.reaction.sourceTypes.patent}</option><option value="database">{t.reaction.sourceTypes.database}</option><option value="url">{t.reaction.sourceTypes.webpage}</option><option value="other">{t.reaction.sourceTypes.other}</option></select></label>
          <label>DOI<input name="doi" defaultValue={details?.doi || ""} maxLength={300} required={sourceType === "doi"} disabled={busy} /></label>
          <label>{t.submit.patent}<input name="patent" defaultValue={details?.patent || ""} maxLength={300} required={sourceType === "patent"} disabled={busy} /></label>
          <label className="wide">{t.submit.sourceLink}<input name="source_url" type="url" defaultValue={details?.publication_url || ""} maxLength={1000} required={sourceType === "url"} disabled={busy} /></label>
          <label className="wide">{t.submit.sourceNote}<input name="source_citation" defaultValue={details?.source_citation || ""} placeholder={t.submit.sourceNoteHint} maxLength={2000} required={sourceType === "database" || sourceType === "other"} disabled={busy} /></label>
        </div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><span>STRUCTURE</span><div><h2>{t.submit.participants}</h2><p>{t.submit.participantsHint}</p></div></div>
        <div className="participant-editor-cards">
          {participants.map((item) => <article className="participant-input-card" key={item.key}>
            <div className="participant-input-main">
              <select value={item.role} onChange={(event) => update(item.key, { role: event.target.value as Role })} disabled={busy}>{Object.entries(roleLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
              <input value={item.smiles} onChange={(event) => update(item.key, { smiles: event.target.value })} placeholder="SMILES" maxLength={4000} disabled={busy} />
              <button type="button" onClick={() => setParticipants((current) => current.filter((row) => row.key !== item.key))} disabled={busy || participants.length <= 2}>{t.common.delete}</button>
            </div>
            <div className="participant-measures">
              <label>{t.submit.occurrenceCount}<input type="number" min="1" max="20" value={item.occurrence_count} onChange={(event) => update(item.key, { occurrence_count: event.target.value })} /></label>
              <label>{t.submit.amount}<input type="number" min="0" step="any" value={item.amount_value} onChange={(event) => update(item.key, { amount_value: event.target.value })} /></label>
              <label>{t.submit.unit}<input value={item.amount_unit} onChange={(event) => update(item.key, { amount_unit: event.target.value })} placeholder="mmol" maxLength={40} /></label>
              <label>{t.submit.equivalents}<input type="number" min="0" step="any" value={item.equivalents} onChange={(event) => update(item.key, { equivalents: event.target.value })} /></label>
              <label>{t.submit.concentration}<input type="number" min="0" step="any" value={item.concentration_value} onChange={(event) => update(item.key, { concentration_value: event.target.value })} /></label>
              <label>{t.submit.concUnit}<input value={item.concentration_unit} onChange={(event) => update(item.key, { concentration_unit: event.target.value })} placeholder="mol/L" maxLength={40} /></label>
              {item.role === "PRODUCT" && <label>{t.submit.yield}<input type="number" min="0" max="100" step="any" value={item.yield_percent} onChange={(event) => update(item.key, { yield_percent: event.target.value })} /></label>}
            </div>
          </article>)}
        </div>
        <div className="participant-add">{(Object.keys(roleLabel) as Role[]).map((role) => <button type="button" key={role} disabled={busy || participants.length >= 100} onClick={() => setParticipants((current) => [...current, blank(role)])}>+ {roleLabel[role]}</button>)}</div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><span>PROCESS</span><div><h2>{t.submit.procedureConditions}</h2><p>{t.submit.procedureHint}</p></div></div>
        <div className="form-fields">
          <label>{t.submit.procedure}<textarea name="procedure_details" rows={7} defaultValue={details?.procedure_details || ""} maxLength={30000} /></label>
          <div className="condition-fields">
            <label>{t.submit.temperature}<input name="temperature_value" type="number" step="any" defaultValue={details?.temperature?.value ?? ""} /></label><label>{t.submit.unit}<select name="temperature_unit" defaultValue={details?.temperature?.unit || "CELSIUS"}><option value="CELSIUS">°C</option><option value="KELVIN">K</option></select></label>
            <label>{t.submit.time}<input name="duration_value" type="number" min="0.000001" step="any" defaultValue={details?.duration?.value ?? ""} /></label><label>{t.submit.unit}<select name="duration_unit" defaultValue={details?.duration?.unit || "HOUR"}><option value="MINUTE">{t.reaction.timeUnits.minute}</option><option value="HOUR">{t.reaction.timeUnits.hour}</option><option value="DAY">{t.reaction.timeUnits.day}</option></select></label>
            <label>pH<input name="ph" type="number" min="0" max="14" step="any" defaultValue={details?.ph ?? ""} /></label><label>{t.submit.atmosphere}<input name="atmosphere" defaultValue={details?.atmosphere || ""} maxLength={120} /></label>
            <label>{t.submit.pressure}<input name="pressure_value" type="number" min="0.000001" step="any" defaultValue={details?.pressure?.value ?? ""} /></label><label>{t.submit.unit}<input name="pressure_unit" defaultValue={details?.pressure?.unit || ""} placeholder="bar" maxLength={40} /></label>
          </div>
          <label>{t.submit.otherConditions}<textarea name="conditions_detail" rows={3} defaultValue={details?.conditions_detail || ""} maxLength={10000} /></label>
          <label>{t.submit.workup}<textarea name="workup_details" rows={3} defaultValue={details?.workup_details || ""} maxLength={10000} /></label>
          <label>{t.submit.safety}<textarea name="safety_notes" rows={3} defaultValue={details?.safety_notes || ""} maxLength={10000} /></label>
          <label>{t.submit.notes}<textarea name="note" rows={3} defaultValue={details?.note || ""} maxLength={10000} /></label>
        </div>
      </section>
      {message && <p className="form-message bad">{message}</p>}
      <button type="submit" className="button primary submit-button" disabled={busy}>{busy ? t.submit.submitting : reactionId ? t.submit.submitEdit : visibility === "private" ? t.submit.submitPrivate : t.submit.submitPublic}</button>
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
  if (!participants.some((item) => item.role === "REACTANT") || !participants.some((item) => item.role === "PRODUCT")) return t.submit.errReactantProduct;
  if (participants.some((item) => (item.amount_value == null) !== (item.amount_unit == null))) return t.submit.errAmountUnit;
  if (participants.some((item) => (item.concentration_value == null) !== (item.concentration_unit == null))) return t.submit.errConcUnit;
  const requiredSource: Partial<Record<SourceType, string>> = { doi: "doi", patent: "patent", database: "source_citation", url: "source_url", other: "source_citation" };
  const sourceField = requiredSource[sourceType];
  if (sourceField && !optional(values, sourceField)) return t.submit.errSourceMissing;
  return "";
}
