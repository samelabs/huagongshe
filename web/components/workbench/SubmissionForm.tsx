"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet, apiPost, apiPut, ApiError, type ReactionDetail } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { SaveStatus, type SaveStatusKind } from "./SaveStatus";
import { useUnsavedGuard } from "./useUnsavedGuard";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

type Role = "REACTANT" | "PRODUCT" | "REAGENT" | "CATALYST" | "SOLVENT";
type SourceType = "self" | "doi" | "patent" | "database" | "url" | "other";
type Participant = {
  key: number; role: Role; smiles: string; occurrence_count: string;
  amount_value: string; amount_unit: string; equivalents: string;
  concentration_value: string; concentration_unit: string; yield_percent: string;
};
/** 校验错误定位到字段：participants = 组分区（焦点到第一个 SMILES） */
type FieldErrors = Partial<Record<"participants" | "doi" | "patent" | "source_url" | "source_citation", string>>;

let sequence = 1;
const blank = (role: Role, smiles = ""): Participant => ({
  key: sequence++, role, smiles, occurrence_count: "1", amount_value: "", amount_unit: "",
  equivalents: "", concentration_value: "", concentration_unit: "", yield_percent: "",
});

/**
 * SubmissionForm — /submit 反应录入（Step 9 Part C IX-5）。
 * - 字段全部 Field 组件化（label 在上、错误在字段下方）；noValidate 关掉
 *   原生气泡，校验统一走 validateDraft → 错误落在对应 Field，提交后焦点
 *   移到第一个出错字段。
 * - 保存状态（IX-5）：提交中 / 保存失败（Notice err + 内容保留）/ 有未保存
 *   修改（站内路由 useConfirm 拦截 + beforeunload）。
 * - 提交按钮 IX-4：loading + 幂等键防重复提交（沿用既有逻辑）。
 */
export function SubmissionForm() {
  const search = useSearchParams();
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const formRef = useRef<HTMLFormElement>(null);
  // 角色标签跟随当前请求字典(原模块级常量依赖静态 zh 字典)
  const roleLabel: Record<Role, string> = {
    REACTANT: t.submit.roles.reactant, PRODUCT: t.submit.roles.product, REAGENT: t.submit.roles.reagent, CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
  };
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
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [dirty, setDirty] = useState(false);
  const submitting = useRef(false);
  const idempotency = useRef({ key: "", body: "" });

  useUnsavedGuard(dirty);

  useEffect(() => {
    let active = true;
    if (reactionId) {
      setEditState("loading");
      setDetails(null);
      setParticipants([blank("REACTANT"), blank("PRODUCT")]);
      setVisibility("private");
      setMessage("");
      setFieldErrors({});
      setDirty(false);
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
    setFieldErrors({});
    setDirty(false);
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

  /** 提交后焦点移到第一个出错字段（participants → 第一个 SMILES 输入） */
  function focusFirstError(errors: FieldErrors) {
    if (errors.participants) {
      formRef.current?.querySelector<HTMLInputElement>("input[data-field='smiles']")?.focus();
      return;
    }
    const name = Object.keys(errors)[0];
    if (name) formRef.current?.querySelector<HTMLElement>(`[name="${name}"]`)?.focus();
  }

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
      pressure_value: optional(values, "pressure_value"),
      pressure_unit: optional(values, "pressure_value") ? optional(values, "pressure_unit") : null,
      workup_details: optional(values, "workup_details"), safety_notes: optional(values, "safety_notes"),
      source_type: values.get("source_type"), doi: optional(values, "doi"),
      patent: optional(values, "patent"), source_url: optional(values, "source_url"),
      source_citation: optional(values, "source_citation"), note: optional(values, "note"),
    };
    const validationError = validateDraft(normalized, values, sourceType, t);
    if (validationError) {
      const errors: FieldErrors = { [validationError.field]: validationError.message };
      setFieldErrors(errors);
      setMessage("");
      focusFirstError(errors);
      return;
    }
    setFieldErrors({});

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
      setDirty(false);
      router.push(withLocale(`/reaction/${body.id}`, locale));
      router.refresh();
    } catch (err) {
      // IX-5：失败保留全部输入内容（defaultValue / state 均不动），页面级 Notice。
      setMessage(err instanceof ApiError ? t.submit.errSave : t.submit.errNetwork);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const status: SaveStatusKind | null = busy ? "saving" : message ? "failed" : dirty ? "dirty" : null;

  const queryString = search.toString();
  const nextPath = `/submit${queryString ? `?${queryString}` : ""}`;
  if (!ready) return <p className="context-loading">{t.common.loadingAccount}</p>;
  if (!user) return <div className="auth-required"><div><strong>{t.submit.loginRequired}</strong><span>{t.submit.loginHint}</span></div><Link href={withLocale(`/login?next=${encodeURIComponent(nextPath)}`, locale)}>{t.common.loginOrRegister}</Link></div>;
  if (reactionId && editState === "loading") return <p className="context-loading">{t.submit.readingRecord}</p>;
  if (reactionId && editState === "error") return <p className="form-message bad">{message}</p>;

  return (
    <form
      className="structured-form"
      onSubmit={submit}
      onChange={() => { if (!dirty) setDirty(true); }}
      key={details?.updated_at || "new"}
      aria-busy={busy}
      noValidate
      ref={formRef}
    >
      {reactionId && <div className="editing-context"><span>{t.submit.editing}</span><EntityId kind="reaction" id={reactionId} compact /></div>}
      <div className="form-section-head-row">
        <SaveStatus status={status} t={t} />
      </div>

      <section className="form-section">
        <div className="form-section-head"><div><h2>{t.submit.visibilitySource}</h2><p>{t.submit.visibilityHint}</p></div></div>
        <div className="form-fields two-columns">
          <Field label={t.submit.visibility} htmlFor="sf-visibility">
            <Select id="sf-visibility" name="visibility" value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "private")} disabled={busy}>
              <option value="private">{t.submit.privateRecord}</option>
              <option value="public">{t.submit.publicRecord}</option>
            </Select>
          </Field>
          <Field label={t.submit.sourceType} htmlFor="sf-source">
            <Select id="sf-source" name="source_type" value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} disabled={busy}>
              <option value="self">{t.reaction.sourceTypes.personal}</option>
              <option value="doi">{t.reaction.sourceTypes.literature} DOI</option>
              <option value="patent">{t.reaction.sourceTypes.patent}</option>
              <option value="database">{t.reaction.sourceTypes.database}</option>
              <option value="url">{t.reaction.sourceTypes.webpage}</option>
              <option value="other">{t.reaction.sourceTypes.other}</option>
            </Select>
          </Field>
          <Field label="DOI" htmlFor="sf-doi" error={fieldErrors.doi}>
            <Input id="sf-doi" name="doi" defaultValue={details?.doi || ""} maxLength={300} disabled={busy} invalid={!!fieldErrors.doi} />
          </Field>
          <Field label={t.submit.patent} htmlFor="sf-patent" error={fieldErrors.patent}>
            <Input id="sf-patent" name="patent" defaultValue={details?.patent || ""} maxLength={300} disabled={busy} invalid={!!fieldErrors.patent} />
          </Field>
          <Field label={t.submit.sourceLink} htmlFor="sf-url" className="wide" error={fieldErrors.source_url}>
            <Input id="sf-url" name="source_url" type="url" defaultValue={details?.publication_url || ""} maxLength={1000} disabled={busy} invalid={!!fieldErrors.source_url} />
          </Field>
          <Field label={t.submit.sourceNote} htmlFor="sf-citation" className="wide" help={t.submit.sourceNoteHint} error={fieldErrors.source_citation}>
            <Input id="sf-citation" name="source_citation" defaultValue={details?.source_citation || ""} maxLength={2000} disabled={busy} invalid={!!fieldErrors.source_citation} />
          </Field>
        </div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><div><h2>{t.submit.participants}</h2><p>{t.submit.participantsHint}</p></div></div>
        {fieldErrors.participants && <Notice tone="err">{fieldErrors.participants}</Notice>}
        <div className="participant-editor-cards">
          {participants.map((item) => <article className="participant-input-card" key={item.key}>
            <div className="participant-input-main">
              <Select value={item.role} onChange={(event) => update(item.key, { role: event.target.value as Role })} disabled={busy} aria-label={t.submit.participants}>{Object.entries(roleLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</Select>
              <Input data-field="smiles" mono value={item.smiles} onChange={(event) => update(item.key, { smiles: event.target.value })} placeholder="SMILES" maxLength={4000} disabled={busy} aria-label="SMILES" />
              <Button variant="ghost" size="sm" type="button" onClick={() => { setDirty(true); setParticipants((current) => current.filter((row) => row.key !== item.key)); }} disabled={busy || participants.length <= 2}>{t.common.delete}</Button>
            </div>
            <div className="participant-measures">
              <Field label={t.submit.occurrenceCount}><Input type="number" min="1" max="20" value={item.occurrence_count} onChange={(event) => update(item.key, { occurrence_count: event.target.value })} /></Field>
              <Field label={t.submit.amount}><Input type="number" min="0" step="any" value={item.amount_value} onChange={(event) => update(item.key, { amount_value: event.target.value })} /></Field>
              <Field label={t.submit.unit}><Input value={item.amount_unit} onChange={(event) => update(item.key, { amount_unit: event.target.value })} placeholder="mmol" maxLength={40} /></Field>
              <Field label={t.submit.equivalents}><Input type="number" min="0" step="any" value={item.equivalents} onChange={(event) => update(item.key, { equivalents: event.target.value })} /></Field>
              <Field label={t.submit.concentration}><Input type="number" min="0" step="any" value={item.concentration_value} onChange={(event) => update(item.key, { concentration_value: event.target.value })} /></Field>
              <Field label={t.submit.concUnit}><Input value={item.concentration_unit} onChange={(event) => update(item.key, { concentration_unit: event.target.value })} placeholder="mol/L" maxLength={40} /></Field>
              {item.role === "PRODUCT" && <Field label={t.submit.yield}><Input type="number" min="0" max="100" step="any" value={item.yield_percent} onChange={(event) => update(item.key, { yield_percent: event.target.value })} /></Field>}
            </div>
          </article>)}
        </div>
        <div className="participant-add">{(Object.keys(roleLabel) as Role[]).map((role) => <Button variant="ghost" size="sm" type="button" key={role} disabled={busy || participants.length >= 100} onClick={() => { setDirty(true); setParticipants((current) => [...current, blank(role)]); }}>+ {roleLabel[role]}</Button>)}</div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><div><h2>{t.submit.procedureConditions}</h2><p>{t.submit.procedureHint}</p></div></div>
        <div className="form-fields">
          <Field label={t.submit.procedure} htmlFor="sf-procedure">
            <Textarea id="sf-procedure" name="procedure_details" rows={7} defaultValue={details?.procedure_details || ""} maxLength={30000} />
          </Field>
          <div className="condition-fields">
            <Field label={t.submit.temperature}><Input name="temperature_value" type="number" step="any" defaultValue={details?.temperature?.value ?? ""} /></Field>
            <Field label={t.submit.unit}><Select name="temperature_unit" defaultValue={details?.temperature?.unit || "CELSIUS"}><option value="CELSIUS">°C</option><option value="KELVIN">K</option></Select></Field>
            <Field label={t.submit.time}><Input name="duration_value" type="number" min="0.000001" step="any" defaultValue={details?.duration?.value ?? ""} /></Field>
            <Field label={t.submit.unit}><Select name="duration_unit" defaultValue={details?.duration?.unit || "HOUR"}><option value="MINUTE">{t.reaction.timeUnits.minute}</option><option value="HOUR">{t.reaction.timeUnits.hour}</option><option value="DAY">{t.reaction.timeUnits.day}</option></Select></Field>
            <Field label="pH"><Input name="ph" type="number" min="0" max="14" step="any" defaultValue={details?.ph ?? ""} /></Field>
            <Field label={t.submit.atmosphere}><Input name="atmosphere" defaultValue={details?.atmosphere || ""} maxLength={120} /></Field>
            <Field label={t.submit.pressure}><Input name="pressure_value" type="number" min="0.000001" step="any" defaultValue={details?.pressure?.value ?? ""} /></Field>
            <Field label={t.submit.unit}><Input name="pressure_unit" defaultValue={details?.pressure?.unit || ""} placeholder="bar" maxLength={40} /></Field>
          </div>
          <Field label={t.submit.otherConditions}><Textarea name="conditions_detail" rows={3} defaultValue={details?.conditions_detail || ""} maxLength={10000} /></Field>
          <Field label={t.submit.workup}><Textarea name="workup_details" rows={3} defaultValue={details?.workup_details || ""} maxLength={10000} /></Field>
          <Field label={t.submit.safety}><Textarea name="safety_notes" rows={3} defaultValue={details?.safety_notes || ""} maxLength={10000} /></Field>
          <Field label={t.submit.notes}><Textarea name="note" rows={3} defaultValue={details?.note || ""} maxLength={10000} /></Field>
        </div>
      </section>
      {message && <Notice tone="err">{message}</Notice>}
      <Button variant="primary" type="submit" className="submit-button" loading={busy}>
        {reactionId ? t.submit.submitEdit : visibility === "private" ? t.submit.submitPrivate : t.submit.submitPublic}
      </Button>
    </form>
  );

  function update(key: number, patch: Partial<Participant>) {
    setDirty(true);
    setParticipants((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
  }
}

function numberParam(value: string | null) { return /^\d+$/.test(value || "") ? Number(value) : null; }
function textOrNull(value: string) { const result = value.trim(); return result || null; }
function numberOrNull(value: string) { return value.trim() === "" ? null : Number(value); }
function optional(values: FormData, key: string) { return textOrNull(String(values.get(key) || "")); }
function optionalNumber(values: FormData, key: string) { const value = optional(values, key); return value == null ? null : Number(value); }
/** 校验错误定位到字段（错误显示在对应 Field 下方 / 组分区 Notice） */
function validateDraft(participants: Array<{ role: Role; amount_value: number | null; amount_unit: string | null; concentration_value: number | null; concentration_unit: string | null }>, values: FormData, sourceType: SourceType, labels: Dictionary): { field: "participants" | "doi" | "patent" | "source_url" | "source_citation"; message: string } | null {
  if (!participants.some((item) => item.role === "REACTANT") || !participants.some((item) => item.role === "PRODUCT")) return { field: "participants", message: labels.submit.errReactantProduct };
  if (participants.some((item) => (item.amount_value == null) !== (item.amount_unit == null))) return { field: "participants", message: labels.submit.errAmountUnit };
  if (participants.some((item) => (item.concentration_value == null) !== (item.concentration_unit == null))) return { field: "participants", message: labels.submit.errConcUnit };
  const requiredSource: Partial<Record<SourceType, "doi" | "patent" | "source_citation" | "source_url">> = { doi: "doi", patent: "patent", database: "source_citation", url: "source_url", other: "source_citation" };
  const sourceField = requiredSource[sourceType];
  if (sourceField && !optional(values, sourceField)) return { field: sourceField, message: labels.submit.errSourceMissing };
  return null;
}
