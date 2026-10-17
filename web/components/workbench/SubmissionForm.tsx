"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet, apiPost, apiPut, ApiError, apiErrorMessage, type ReactionDetail } from "@/lib/api";
import { DOI_RE, REACTION_RULES } from "@/lib/reactionRules";
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

/** 参与物行内可报错的输入（__row = 无法归属具体输入的行级错误） */
type ParticipantErrors = Partial<Record<"__row" | "smiles" | "occurrence_count" | "amount_value" | "equivalents" | "concentration_value" | "yield_percent", string>>;
/** 错误定位：顶层字段 → 对应 Field；rows → 第 N 个参与物的具体输入；
 *  participants → 组分区整体（无法归属行时）；三者之外才落页级 Notice。 */
type FieldErrors = Partial<Record<"doi" | "patent" | "source_url" | "source_citation" | "temperature_value" | "duration_value" | "ph" | "pressure_value", string>> & {
  rows?: Record<number, ParticipantErrors>;
  participants?: string;
};

let sequence = 1;
const blank = (role: Role, smiles = ""): Participant => ({
  key: sequence++, role, smiles, occurrence_count: "1", amount_value: "", amount_unit: "",
  equivalents: "", concentration_value: "", concentration_unit: "", yield_percent: "",
});

/** 后端 422/409 的 field 路径（如 participants.2.smiles）→ 表单错误定位。 */
function mapBackendField(field: string, detail: string, rowKeys: number[]): { rowKey?: number; subField?: string; topField?: string } | null {
  const participant = /^participants\.(\d+)(?:\.(\w+))?$/.exec(field);
  if (participant) {
    const index = Number(participant[1]);
    if (index < rowKeys.length) {
      return { rowKey: rowKeys[index], subField: participant[2] || "__row" };
    }
    return null;
  }
  if (/^[a-z_]+$/.test(field)) return { topField: field };
  return null;
}

/** 后端 message 的「字段路径前缀」不进用户文案（错误已渲染在对应输入下）。 */
function stripFieldPrefix(message: string, field: string): string {
  return message.replace(new RegExp(`^${field.replace(/\./g, "\\.")}：`), "");
}

/**
 * SubmissionForm — /submit 反应录入。
 * - 字段全部 Field 组件化（label 在上、错误在字段下方）；noValidate 关掉
 *   原生气泡，提交前校验与后端 schema 同源（lib/reactionRules.ts 单一
 *   来源，配对账测试），错误落在对应 Field，提交后焦点移到第一个出错
 *   字段（aria-invalid 的首个控件，按文档顺序）。
 * - 保存状态：提交中 / 保存失败（Notice err + 内容保留）/ 有未保存
 *   修改（站内路由 useConfirm 拦截 + beforeunload）。
 * - 提交按钮：loading + 幂等键防重复提交（同表单内容复用同一幂等键）。
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
  /** 异步预填回调读最新脏态 —— 用户已输入时不覆盖 */
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  const submitting = useRef(false);
  const idempotency = useRef({ key: "", body: "" });
  /** 本轮提交的参与物行 key 序（后端按过滤后的行序报字段路径） */
  const submittedRowKeys = useRef<number[]>([]);

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
        if (active && chemical.smiles && !dirtyRef.current) setParticipants([blank("REACTANT", chemical.smiles), blank("PRODUCT")]);
      }).catch(() => {});
      return () => { active = false; };
    }
    setParticipants([blank("REACTANT"), blank("PRODUCT")]);
    return () => { active = false; };
  }, [reactionId, chemicalId]);

  /** 提交后焦点移到第一个出错字段（文档序第一个 aria-invalid 控件） */
  function focusFirstError() {
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || (reactionId && editState !== "ready")) return;
    if (!user) { setMessage(t.submit.errNotLogin); return; }
    const values = new FormData(event.currentTarget);
    const filledRows = participants.filter((item) => item.smiles.trim());
    const normalized = filledRows.map((item) => ({
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
      pressure_unit: optionalNumber(values, "pressure_value") ? optional(values, "pressure_unit") : null,
      workup_details: optional(values, "workup_details"), safety_notes: optional(values, "safety_notes"),
      source_type: values.get("source_type"), doi: optional(values, "doi"),
      patent: optional(values, "patent"), source_url: optional(values, "source_url"),
      source_citation: optional(values, "source_citation"), note: optional(values, "note"),
    };
    submittedRowKeys.current = filledRows.map((row) => row.key);
    const validationErrors = validateDraft(filledRows, values, sourceType, t);
    if (validationErrors) {
      setFieldErrors(validationErrors);
      setMessage("");
      requestAnimationFrame(focusFirstError);
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
      // 失败保留全部输入内容（defaultValue / state 均不动）。
      // 错误定位：后端 field 路径映射到对应输入；无法归属字段的错误才
      // 落页级 Notice。
      if (err instanceof ApiError && (err.detailKind === "invalid_field" || err.detailField)) {
        const errors = mapBackendError(err, submittedRowKeys.current, t);
        if (errors) {
          setFieldErrors(errors);
          setMessage("");
          requestAnimationFrame(focusFirstError);
          return;
        }
      }
      setFieldErrors({});
      setMessage(apiErrorMessage(err, t, t.submit.errSave));
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
      method="post"
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
            <Input id="sf-doi" name="doi" defaultValue={details?.doi || ""} maxLength={REACTION_RULES.doiMaxLength} disabled={busy} invalid={!!fieldErrors.doi} />
          </Field>
          <Field label={t.submit.patent} htmlFor="sf-patent" error={fieldErrors.patent}>
            <Input id="sf-patent" name="patent" defaultValue={details?.patent || ""} maxLength={REACTION_RULES.patentMaxLength} disabled={busy} invalid={!!fieldErrors.patent} />
          </Field>
          <Field label={t.submit.sourceLink} htmlFor="sf-url" className="wide" error={fieldErrors.source_url}>
            <Input id="sf-url" name="source_url" type="url" defaultValue={details?.publication_url || ""} maxLength={REACTION_RULES.sourceUrlMaxLength} disabled={busy} invalid={!!fieldErrors.source_url} />
          </Field>
          <Field label={t.submit.sourceNote} htmlFor="sf-citation" className="wide" help={t.submit.sourceNoteHint} error={fieldErrors.source_citation}>
            <Input id="sf-citation" name="source_citation" defaultValue={details?.source_citation || ""} maxLength={REACTION_RULES.sourceCitationMaxLength} disabled={busy} invalid={!!fieldErrors.source_citation} />
          </Field>
        </div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><div><h2>{t.submit.participants}</h2><p>{t.submit.participantsHint}</p></div></div>
        {fieldErrors.participants && <Notice tone="err">{fieldErrors.participants}</Notice>}
        <div className="participant-editor-cards">
          {participants.map((item) => {
            const rowError = fieldErrors.rows?.[item.key];
            return <article className="participant-input-card" key={item.key}>
            <div className="participant-input-main">
              <Select value={item.role} onChange={(event) => update(item.key, { role: event.target.value as Role })} disabled={busy} aria-label={t.submit.participants}>{Object.entries(roleLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</Select>
              <Input data-field="smiles" mono value={item.smiles} onChange={(event) => update(item.key, { smiles: event.target.value })} placeholder="SMILES" maxLength={REACTION_RULES.smilesMaxLength} disabled={busy} aria-label="SMILES" invalid={!!rowError?.smiles} aria-invalid={rowError?.smiles ? true : undefined} />
              <Button variant="ghost" size="sm" type="button" onClick={() => { setDirty(true); setParticipants((current) => current.filter((row) => row.key !== item.key)); }} disabled={busy || participants.length <= REACTION_RULES.participantsMin}>{t.common.delete}</Button>
            </div>
            {(rowError?.smiles || rowError?.__row) && <p className="hg-help err participant-row-error">{rowError?.smiles || rowError?.__row}</p>}
            <div className="participant-measures">
              <Field label={t.submit.occurrenceCount} error={rowError?.occurrence_count}><Input type="number" min={REACTION_RULES.occurrenceCountMin} max={REACTION_RULES.occurrenceCountMax} step="1" value={item.occurrence_count} invalid={!!rowError?.occurrence_count} onChange={(event) => update(item.key, { occurrence_count: event.target.value })} /></Field>
              <Field label={t.submit.amount} error={rowError?.amount_value}><Input type="number" min={REACTION_RULES.nonNegativeMin} step="any" value={item.amount_value} invalid={!!rowError?.amount_value} onChange={(event) => update(item.key, { amount_value: event.target.value })} /></Field>
              <Field label={t.submit.unit}><Input value={item.amount_unit} onChange={(event) => update(item.key, { amount_unit: event.target.value })} placeholder="mmol" maxLength={REACTION_RULES.amountUnitMaxLength} /></Field>
              <Field label={t.submit.equivalents} error={rowError?.equivalents}><Input type="number" min={REACTION_RULES.nonNegativeMin} step="any" value={item.equivalents} invalid={!!rowError?.equivalents} onChange={(event) => update(item.key, { equivalents: event.target.value })} /></Field>
              <Field label={t.submit.concentration} error={rowError?.concentration_value}><Input type="number" min={REACTION_RULES.nonNegativeMin} step="any" value={item.concentration_value} invalid={!!rowError?.concentration_value} onChange={(event) => update(item.key, { concentration_value: event.target.value })} /></Field>
              <Field label={t.submit.concUnit}><Input value={item.concentration_unit} onChange={(event) => update(item.key, { concentration_unit: event.target.value })} placeholder="mol/L" maxLength={REACTION_RULES.amountUnitMaxLength} /></Field>
              {item.role === "PRODUCT" && <Field label={t.submit.yield} error={rowError?.yield_percent}><Input type="number" min={REACTION_RULES.yieldMin} max={REACTION_RULES.yieldMax} step="any" value={item.yield_percent} invalid={!!rowError?.yield_percent} onChange={(event) => update(item.key, { yield_percent: event.target.value })} /></Field>}
            </div>
          </article>;
          })}
        </div>
        <div className="participant-add">{(Object.keys(roleLabel) as Role[]).map((role) => <Button variant="ghost" size="sm" type="button" key={role} disabled={busy || participants.length >= REACTION_RULES.participantsMax} onClick={() => { setDirty(true); setParticipants((current) => [...current, blank(role)]); }}>+ {roleLabel[role]}</Button>)}</div>
      </section>

      <section className="form-section">
        <div className="form-section-head"><div><h2>{t.submit.procedureConditions}</h2><p>{t.submit.procedureHint}</p></div></div>
        <div className="form-fields">
          <Field label={t.submit.procedure} htmlFor="sf-procedure">
            <Textarea id="sf-procedure" name="procedure_details" rows={7} defaultValue={details?.procedure_details || ""} maxLength={REACTION_RULES.procedureMaxLength} />
          </Field>
          <div className="condition-fields">
            <Field label={t.submit.temperature} error={fieldErrors.temperature_value}><Input name="temperature_value" type="number" step="any" defaultValue={details?.temperature?.value ?? ""} invalid={!!fieldErrors.temperature_value} /></Field>
            <Field label={t.submit.unit}><Select name="temperature_unit" defaultValue={details?.temperature?.unit || "CELSIUS"}><option value="CELSIUS">°C</option><option value="KELVIN">K</option></Select></Field>
            <Field label={t.submit.time} error={fieldErrors.duration_value}><Input name="duration_value" type="number" min="0.000001" step="any" defaultValue={details?.duration?.value ?? ""} invalid={!!fieldErrors.duration_value} /></Field>
            <Field label={t.submit.unit}><Select name="duration_unit" defaultValue={details?.duration?.unit || "HOUR"}><option value="MINUTE">{t.reaction.timeUnits.minute}</option><option value="HOUR">{t.reaction.timeUnits.hour}</option><option value="DAY">{t.reaction.timeUnits.day}</option></Select></Field>
            <Field label="pH" error={fieldErrors.ph}><Input name="ph" type="number" min={REACTION_RULES.phMin} max={REACTION_RULES.phMax} step="any" defaultValue={details?.ph ?? ""} invalid={!!fieldErrors.ph} /></Field>
            <Field label={t.submit.atmosphere}><Input name="atmosphere" defaultValue={details?.atmosphere || ""} maxLength={REACTION_RULES.atmosphereMaxLength} /></Field>
            <Field label={t.submit.pressure} error={fieldErrors.pressure_value}><Input name="pressure_value" type="number" min="0.000001" step="any" defaultValue={details?.pressure?.value ?? ""} invalid={!!fieldErrors.pressure_value} /></Field>
            <Field label={t.submit.unit}><Input name="pressure_unit" defaultValue={details?.pressure?.unit || ""} placeholder="bar" maxLength={REACTION_RULES.amountUnitMaxLength} /></Field>
          </div>
          <Field label={t.submit.otherConditions}><Textarea name="conditions_detail" rows={3} defaultValue={details?.conditions_detail || ""} maxLength={REACTION_RULES.textAreaMaxLength} /></Field>
          <Field label={t.submit.workup}><Textarea name="workup_details" rows={3} defaultValue={details?.workup_details || ""} maxLength={REACTION_RULES.textAreaMaxLength} /></Field>
          <Field label={t.submit.safety}><Textarea name="safety_notes" rows={3} defaultValue={details?.safety_notes || ""} maxLength={REACTION_RULES.textAreaMaxLength} /></Field>
          <Field label={t.submit.notes}><Textarea name="note" rows={3} defaultValue={details?.note || ""} maxLength={REACTION_RULES.textAreaMaxLength} /></Field>
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

/** 后端错误 → 表单错误定位；返回 null 表示无法归属字段（走页级 Notice） */
function mapBackendError(err: ApiError, rowKeys: number[], t: Dictionary): FieldErrors | null {
  const { detailField: backendField = "", detail: backendDetail = "", detailKind: kind = "" } = err;
  // 结构/重复参与物：后端带参与物行号，前端按字典文案定位到该行
  if (kind === "invalid_structure" || kind === "invalid_reaction") {
    const mapped = backendField ? mapBackendField(backendField, backendDetail, rowKeys) : null;
    if (mapped?.rowKey != null) {
      return { rows: { [mapped.rowKey]: { [mapped.subField === "__row" ? "__row" : "smiles"]: t.errors[kind] || backendDetail } } };
    }
    return null;
  }
  if (kind === "duplicate_participant") {
    const mapped = backendField ? mapBackendField(backendField, backendDetail, rowKeys) : null;
    if (mapped?.rowKey != null) {
      return { rows: { [mapped.rowKey]: { __row: t.errors.duplicate_participant } } };
    }
    return null;
  }
  if (kind !== "invalid_field" || !backendField) return null;
  const mapped = mapBackendField(backendField, backendDetail, rowKeys);
  const text = stripFieldPrefix(backendDetail, backendField) || backendDetail;
  if (!mapped) return null;
  if (mapped.rowKey != null) {
    const subField = mapped.subField === "__row" || mapped.subField === "smiles"
      ? (mapped.subField === "smiles" ? "smiles" : "__row")
      : (mapped.subField as "occurrence_count" | "amount_value" | "equivalents" | "concentration_value" | "yield_percent");
    return { rows: { [mapped.rowKey]: { [subField]: text } } };
  }
  const known: Record<string, keyof FieldErrors> = {
    doi: "doi", patent: "patent", source_url: "source_url", source_citation: "source_citation",
    temperature_value: "temperature_value", duration_value: "duration_value",
    ph: "ph", pressure_value: "pressure_value", pressure_unit: "pressure_value",
  };
  const topField = mapped.topField ? known[mapped.topField] : undefined;
  if (!topField) return null;
  return { [topField]: text } as FieldErrors;
}

/** 提交前校验：与后端 schema 同源（lib/reactionRules.ts），错误定位到具体输入 */
function validateDraft(
  rows: Participant[],
  values: FormData,
  sourceType: SourceType,
  labels: Dictionary,
): FieldErrors | null {
  const errors: FieldErrors = {};
  const rowsOut: Record<number, ParticipantErrors> = {};

  if (rows.length < REACTION_RULES.participantsMin) {
    errors.participants = labels.submit.errReactantProduct;
  } else if (!rows.some((item) => item.role === "REACTANT") || !rows.some((item) => item.role === "PRODUCT")) {
    errors.participants = labels.submit.errReactantProduct;
  }

  for (const item of rows) {
    const row: ParticipantErrors = {};
    const occurrence = Number(item.occurrence_count || 1);
    if (!Number.isInteger(occurrence) || occurrence < REACTION_RULES.occurrenceCountMin || occurrence > REACTION_RULES.occurrenceCountMax) {
      row.occurrence_count = labels.submit.errOccurrenceCount;
    }
    const amount = numberOrNull(item.amount_value);
    const amountUnit = textOrNull(item.amount_unit);
    if ((amount == null) !== (amountUnit == null)) row.amount_value = labels.submit.errAmountUnit;
    else if (amount != null && amount < REACTION_RULES.nonNegativeMin) row.amount_value = labels.submit.errNonNegative;
    const equivalents = numberOrNull(item.equivalents);
    if (equivalents != null && equivalents < REACTION_RULES.nonNegativeMin) row.equivalents = labels.submit.errNonNegative;
    const concentration = numberOrNull(item.concentration_value);
    const concentrationUnit = textOrNull(item.concentration_unit);
    if ((concentration == null) !== (concentrationUnit == null)) row.concentration_value = labels.submit.errConcUnit;
    else if (concentration != null && concentration < REACTION_RULES.nonNegativeMin) row.concentration_value = labels.submit.errNonNegative;
    if (item.role === "PRODUCT") {
      const yieldPercent = numberOrNull(item.yield_percent);
      if (yieldPercent != null && (yieldPercent < REACTION_RULES.yieldMin || yieldPercent > REACTION_RULES.yieldMax)) {
        row.yield_percent = labels.submit.errYieldRange;
      }
    }
    if (Object.keys(row).length > 0) rowsOut[item.key] = row;
  }

  // 配对语义与载荷构造一致：数值缺单位报错；单位无数值时载荷本来就不带
  // （单位选择器恒有默认值，不能把「只填了单位」当违例）。
  const temperatureValue = optionalNumber(values, "temperature_value");
  if (temperatureValue != null && optional(values, "temperature_unit") == null) {
    errors.temperature_value = labels.submit.errTempPair;
  }

  const durationValue = optionalNumber(values, "duration_value");
  if (durationValue != null && optional(values, "duration_unit") == null) {
    errors.duration_value = labels.submit.errDurationPair;
  } else if (durationValue != null && durationValue <= REACTION_RULES.durationExclusiveMin) {
    errors.duration_value = labels.submit.errDurationRange;
  }

  const ph = optionalNumber(values, "ph");
  if (ph != null && (ph < REACTION_RULES.phMin || ph > REACTION_RULES.phMax)) errors.ph = labels.submit.errPhRange;

  const pressureValue = optionalNumber(values, "pressure_value");
  const pressureUnit = optional(values, "pressure_unit");
  if (pressureValue != null && pressureUnit == null) {
    errors.pressure_value = labels.submit.errPressurePair;
  } else if (pressureValue != null && pressureValue <= REACTION_RULES.pressureExclusiveMin) {
    errors.pressure_value = labels.submit.errPressureRange;
  }

  const doi = optional(values, "doi");
  if (doi && !DOI_RE.test(normalizeDoiInput(doi))) errors.doi = labels.submit.errDoiFormat;

  const sourceUrl = optional(values, "source_url");
  if (sourceUrl && !REACTION_RULES.sourceUrlSchemes.some((scheme) => sourceUrl.toLowerCase().startsWith(scheme))) {
    errors.source_url = labels.submit.errSourceUrlScheme;
  }

  const requiredSource = REACTION_RULES.requiredSourceField as Record<string, "doi" | "patent" | "source_citation" | "source_url">;
  const sourceField = requiredSource[sourceType];
  if (sourceField && !optional(values, sourceField)) errors[sourceField] = labels.submit.errSourceMissing;

  if (Object.keys(rowsOut).length > 0) errors.rows = rowsOut;
  return Object.keys(errors).length > 0 ? errors : null;
}

/** 与后端 normalize_doi 同源的宽松归一（剥 DOI 前缀后再做格式判断） */
function normalizeDoiInput(value: string): string {
  let normalized = value.trim();
  for (const prefix of ["https://doi.org/", "http://doi.org/", "doi:"]) {
    if (normalized.toLowerCase().startsWith(prefix)) {
      normalized = normalized.slice(prefix.length).trim();
      break;
    }
  }
  return normalized;
}
