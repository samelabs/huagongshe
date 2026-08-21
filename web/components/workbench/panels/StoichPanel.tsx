"use client";

import { useState } from "react";
import t from "@/lib/i18n";
import { apiPost, ApiError } from "@/lib/api";
import { PanelHeading, WbEmpty } from "../shared";

type Role = "REACTANT" | "REAGENT" | "CATALYST" | "SOLVENT" | "PRODUCT";
type Row = { role: Role; smiles: string; eq: string; label: string };

type Component = {
  role: Role;
  smiles: string;
  label: string | null;
  eq: number | null;
  formula: string | null;
  molar_mass: number;
  mmol: number | null;
  mass_g: number | null;
  volume_ml: number | null;
  is_basis: boolean;
};

type ScaleResult = {
  basis: { formula: string | null; molar_mass: number; mmol: number; mass_g: number };
  components: Component[];
  product_theoretical_yield_g: number | null;
  solvent_volume_ml: number | null;
};

const ROLES: Role[] = ["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"];
const UNITS = ["g", "mg", "mol", "mmol"] as const;
const roleLabel = (r: Role) =>
  ({ REACTANT: t.stoich.roleREACTANT, REAGENT: t.stoich.roleREAGENT, CATALYST: t.stoich.roleCATALYST, SOLVENT: t.stoich.roleSOLVENT, PRODUCT: t.stoich.rolePRODUCT } as const)[r];

const emptyRow = (): Row => ({ role: "REACTANT", smiles: "", eq: "1.0", label: "" });

export function StoichPanel() {
  const [rows, setRows] = useState<Row[]>([emptyRow(), emptyRow()]);
  const [basisIndex, setBasisIndex] = useState(0);
  const [basisAmount, setBasisAmount] = useState("");
  const [basisUnit, setBasisUnit] = useState<(typeof UNITS)[number]>("g");
  const [conc, setConc] = useState("");
  const [result, setResult] = useState<ScaleResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<unknown>(null);

  const setRow = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function calculate() {
    setState("loading");
    setError(null);
    const kept = rows.map((r, i) => ({ r, i })).filter((x) => x.r.smiles.trim() !== "");
    const basisKept = kept.findIndex((x) => x.i === basisIndex);
    if (basisKept < 0) {
      setError(new ApiError(400, t.stoich.errBasisEmpty));
      setState("error");
      return;
    }
    const components = kept.map(({ r }) => ({
      role: r.role,
      smiles: r.smiles.trim(),
      ...(r.role === "SOLVENT" && r.eq.trim() === "" ? {} : { eq: Number(r.eq) }),
      ...(r.label.trim() ? { label: r.label.trim() } : {}),
    }));
    try {
      const data = await apiPost<ScaleResult>("/stoichiometry/scale", JSON.stringify({
        components,
        basis: {
          index: basisKept,
          amount_value: Number(basisAmount),
          amount_unit: basisUnit,
        },
        ...(conc.trim() ? { concentration_mol_per_l: Number(conc) } : {}),
      }));
      setResult(data);
      setState("ready");
    } catch (err) {
      setError(err);
      setState("error");
    }
  }

  return (
    <section className="wb-panel wb-stoich">
      <PanelHeading title={t.stoich.title} subtitle={t.stoich.subtitle} />

      <div className="wb-stoich-form">
        <div className="wb-stoich-thead" role="row">
          <span>{t.stoich.colBasis}</span>
          <span>{t.stoich.colRole}</span>
          <span>{t.stoich.colSmiles}</span>
          <span>{t.stoich.colEq}</span>
          <span>{t.stoich.colLabel}</span>
          <span />
        </div>
        {rows.map((r, i) => (
          <div className="wb-stoich-crow" role="row" key={i}>
            <input
              type="radio"
              name="wb-stoich-basis"
              className="wb-stoich-radio"
              checked={basisIndex === i}
              onChange={() => {
                setBasisIndex(i);
                setRow(i, { eq: "1.0" });
              }}
              aria-label={`${t.stoich.colBasis} ${i + 1}`}
            />
            <select
              className="wb-stoich-select"
              value={r.role}
              onChange={(e) => setRow(i, { role: e.target.value as Role })}
              aria-label={`${t.stoich.colRole} ${i + 1}`}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>{roleLabel(role)}</option>
              ))}
            </select>
            <input
              className="wb-stoich-input wb-stoich-rg-smiles"
              value={r.smiles}
              onChange={(e) => setRow(i, { smiles: e.target.value })}
              placeholder={t.stoich.colSmiles}
              aria-label={`${t.stoich.colSmiles} ${i + 1}`}
            />
            <input
              className="wb-stoich-input wb-stoich-rg-eq"
              type="number"
              min="0"
              step="any"
              value={r.eq}
              onChange={(e) => setRow(i, { eq: e.target.value })}
              aria-label={`${t.stoich.colEq} ${i + 1}`}
            />
            <input
              className="wb-stoich-input wb-stoich-rg-label"
              value={r.label}
              onChange={(e) => setRow(i, { label: e.target.value })}
              placeholder={t.stoich.colLabel}
              aria-label={`${t.stoich.colLabel} ${i + 1}`}
            />
            {rows.length > 2 && (
              <button
                type="button"
                className="wb-btn wb-btn-ghost wb-stoich-remove"
                onClick={() => {
                  setRows((rs) => rs.filter((_, j) => j !== i));
                  setBasisIndex((b) => (i < b ? b - 1 : Math.min(b, rows.length - 2)));
                }}
              >
                {t.stoich.removeComponent}
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          className="wb-btn wb-btn-ghost wb-stoich-add"
          onClick={() => setRows((rs) => [...rs, emptyRow()])}
        >
          {t.stoich.addComponent}
        </button>

        <div className="wb-stoich-basisbox">
          <span className="wb-stoich-ref-title">{t.stoich.basisTitle}</span>
          <div className="wb-stoich-ref-row">
            <input
              className="wb-stoich-input wb-stoich-ref-amount"
              type="number"
              min="0"
              step="any"
              value={basisAmount}
              onChange={(e) => setBasisAmount(e.target.value)}
              placeholder={t.stoich.basisAmount}
              aria-label={t.stoich.basisAmount}
            />
            <select
              className="wb-stoich-select"
              value={basisUnit}
              onChange={(e) => setBasisUnit(e.target.value as (typeof UNITS)[number])}
              aria-label={t.stoich.basisUnit}
            >
              {UNITS.map((u) => (
                <option key={u} value={u}>{u}</option>
              ))}
            </select>
          </div>
          <div className="wb-stoich-ref-row">
            <input
              className="wb-stoich-input wb-stoich-conc"
              type="number"
              min="0"
              step="any"
              value={conc}
              onChange={(e) => setConc(e.target.value)}
              placeholder={t.stoich.concentration}
              aria-label={t.stoich.concentration}
            />
          </div>
        </div>

        <button
          type="button"
          className="wb-btn wb-btn-primary wb-stoich-submit"
          disabled={state === "loading"}
          onClick={calculate}
        >
          {state === "ready" || result ? t.stoich.recalcul : t.stoich.calculate}
        </button>
      </div>

      {state === "error" && (
        <div className="wb-state wb-state-error">
          {error instanceof ApiError && error.status === 400
            ? t.stoich.errInvalid
            : t.me.errPanel}
        </div>
      )}

      {state === "loading" && <div className="wb-state">{t.common.loading}</div>}

      {state === "ready" && result && (
        <div className="wb-stoich-result">
          <span className="wb-stoich-ref-title">{t.stoich.resultTitle}</span>
          <div className="wb-stoich-table" role="table">
            <div className="wb-stoich-rhead" role="row">
              <span>{t.stoich.colName}</span>
              <span>{t.stoich.colRole}</span>
              <span>{t.stoich.colEq}</span>
              <span>{t.stoich.colMmol}</span>
              <span>{t.stoich.colMass}</span>
              <span>{t.stoich.colVolume}</span>
              <span>{t.stoich.colFormula}</span>
              <span>{t.stoich.colMm}</span>
            </div>
            {result.components.map((c, i) => (
              <div className="wb-stoich-rrow" role="row" key={i}>
                <span className="wb-stoich-tname">
                  {c.label || c.smiles}
                  {c.is_basis && <em className="wb-stoich-basis-tag">{t.stoich.basisTag}</em>}
                </span>
                <span>{roleLabel(c.role)}</span>
                <span>{c.eq ?? "—"}</span>
                <span>{c.mmol ?? "—"}</span>
                <span>{c.mass_g != null ? `${c.mass_g} g` : c.volume_ml != null ? t.stoich.solventByConc : "—"}</span>
                <span>{c.volume_ml != null ? `${c.volume_ml} mL` : "—"}</span>
                <span>{c.formula}</span>
                <span>{c.molar_mass}</span>
              </div>
            ))}
          </div>
          {result.product_theoretical_yield_g != null && (
            <div className="wb-stoich-yield">
              <span>{t.stoich.resultYield}（{t.stoich.resultYieldNote}）</span>
              <strong>{result.product_theoretical_yield_g} g</strong>
            </div>
          )}
          {result.solvent_volume_ml != null && (
            <div className="wb-stoich-yield">
              <span>{t.stoich.resultSolvent}</span>
              <strong>{result.solvent_volume_ml} mL</strong>
            </div>
          )}
        </div>
      )}

      {state === "idle" && <WbEmpty text={t.stoich.empty} />}
    </section>
  );
}
