import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { apiGet, isApiGone, isEntityId, type Chemical, type SemanticDetail, type ProseItem, type EvidenceBlock } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { fieldKey, fieldLabel, pathLabel, type FieldLocale } from "@/lib/fieldLabels";
import { withLocale } from "@/lib/localePath";
import "./print.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

function formatNumber(n: number | null | undefined, locale: string, fractionDigits = 4): string {
  if (n == null) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: fractionDigits }).format(n);
}

/** 分区内按字段组织：同一字段只出一行，多来源的值合并去重。 */
type FieldRow = { key: string; label: string; values: string[] };

/** 去重键：空白与大小写归一后比较 —— 逐字的空白差异不算不同的值。 */
function normKey(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
}

function collect(rows: FieldRow[], rawLabel: string, label: string, values: string[]): void {
  const clean = values.filter((v): v is string => Boolean(v));
  if (!clean.length) return;
  const key = fieldKey(rawLabel);
  let row = rows.find((r) => r.key === key);
  if (!row) {
    row = { key, label, values: [] };
    rows.push(row);
  }
  const seen = new Set(row.values.map(normKey));
  for (const value of clean) {
    const dedupeKey = normKey(value);
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    row.values.push(value);
  }
}

/** CB 安全字段的值可能是字符串或嵌套对象（GHS 的说明/象形图/信号词）：
 *  报告里渲染成可读文本列表，不打印 [object Object]，多值逐项返回。 */
function readableSafetyValues(value: unknown, locale: FieldLocale): string[] {
  if (value == null) return [];
  if (typeof value === "string") return value ? [value] : [];
  if (typeof value === "number" || typeof value === "boolean") return [String(value)];
  if (Array.isArray(value)) {
    return value.flatMap((v) => readableSafetyValues(v, locale));
  }
  if (typeof value === "object") {
    return [Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${fieldLabel(k, locale)}: ${readableSafetyValues(v, locale).join(" ")}`)
      .join("; ")];
  }
  return [String(value)];
}

/** 证据条目 → 展示值列表。条目结构为 {路径: 值数组}，每个值项带 value 与可选 unit。 */
function evidenceValues(input: unknown, locale: FieldLocale): string[] {
  const list = Array.isArray(input) ? input : [input];
  const result: string[] = [];
  for (const item of list) {
    if (item == null) continue;
    if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
      result.push(String(item));
      continue;
    }
    if (typeof item === "object") {
      const record = item as Record<string, unknown>;
      const raw = record.value ?? record.name ?? record.description ?? record.text;
      if (Array.isArray(raw)) result.push(...raw.flatMap((v) => readableSafetyValues(v, locale)));
      else if (raw != null) {
        const unit = typeof record.unit === "string" ? record.unit : null;
        for (const text of readableSafetyValues(raw, locale)) {
          result.push(unit ? `${text} ${unit}` : text);
        }
      }
    }
  }
  return result.filter(Boolean);
}

/** 证据块 → 字段行（labels 用当前语言字段名，多值合并）。 */
function evidenceRows(block: EvidenceBlock | null | undefined, locale: FieldLocale): FieldRow[] {
  if (!block || typeof block !== "object") return [];
  const record = block as Record<string, unknown>;
  const entries = record.entries && typeof record.entries === "object"
    ? (record.entries as Record<string, unknown>) : {};
  const rows: FieldRow[] = [];
  for (const [path, values] of Object.entries(entries)) {
    if (["references", "normalization"].includes(path)) continue;
    const label = pathLabel(path, locale);
    collect(rows, path.split(" > ").at(-1) || path, label, evidenceValues(values, locale));
  }
  return rows;
}

/** 无空格的长串（InChI、SMILES、长 URL）允许在任意字符处断开；
 *  普通文本按单词换行，不在字母中间断。 */
function isUnbrokenToken(value: string): boolean {
  return /\S{25,}/.test(value);
}

function FieldTable({ rows }: { rows: FieldRow[] }) {
  if (!rows.length) return null;
  return (
    <table className="pr-table">
      <tbody>
        {rows.map((row) => (
          <tr key={row.key}>
            <th>{row.label}</th>
            <td>
              {row.values.map((value, i) => (
                <span key={i} className={isUnbrokenToken(value) ? "pr-val pr-breakany" : "pr-val"}>
                  {value}
                </span>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ProseSection({ items, skipKeys }: { items: ProseItem[]; skipKeys?: Set<string> }) {
  const visible = items.filter((item) => !item.title || !skipKeys?.has(fieldKey(item.title)));
  if (!visible.length) return null;
  return (
    <>
      {visible.map((item, i) => (
        <div key={i} className="pr-prose-item">
          {item.title && <h3 className="pr-prose-title">{item.title}</h3>}
          <p className="pr-prose-text">{item.text}</p>
        </div>
      ))}
    </>
  );
}

export default async function ChemicalPrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isEntityId(id)) notFound();

  const locale = await getRequestLocale();
  const t = await getRequestDictionary();

  // 语义详情与主记录同源: /chemicals/{id}?enrich=full 的 details 字段。
  const chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=full&locale=${encodeURIComponent(locale)}`).catch((e: unknown) => {
    if (isApiGone(e)) notFound();
    return null;
  });
  if (!chemical) notFound();
  const detail: SemanticDetail | null = chemical.details ?? null;

  const { title } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  const printDate = new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date());
  const pageUrl = `https://huagongshe.com${withLocale(`/chemical/${id}`, locale)}`;

  const names = detail?.names;
  const cbIdentity = names?.cb_identity ?? {};
  const aliases = names?.cb_aliases?.map(a => a.value) ?? [];
  const props = detail?.properties;
  const safety = detail?.safety;
  const industry = detail?.industry;

  const identifierRows: [string, string | null | undefined][] = [
    ["CAS No.", chemical.cas_numbers[0] ?? null],
    [t.chemical.identity.formula, chemical.molecular_formula],
    [t.chemical.identity.avgMass, chemical.average_mass != null ? `${formatNumber(chemical.average_mass, locale)} g/mol` : null],
    [t.chemical.identity.monoMass, chemical.monoisotopic_mass != null ? `${formatNumber(chemical.monoisotopic_mass, locale, 8)} g/mol` : null],
    ["SMILES", chemical.smiles ?? chemical.pubchem_smiles],
    ["InChIKey", chemical.inchikey],
    ["PubChem CID", chemical.pubchem_cid != null ? String(chemical.pubchem_cid) : null],
    ["ChEMBL", chemical.chembl_ids[0] ?? null],
    ["ChEBI", chemical.chebi_ids[0] ?? null],
    ["EC No.", chemical.ec_numbers[0] ?? null],
    ["DTXSID", chemical.dtxsid],
  ].filter(([, v]) => v != null) as [string, string][];

  // ── 性质分区：计算值 + 实验证据 + 实测值 + 说明文本，同一字段只出现一次。
  const propertyRows: FieldRow[] = [];
  const computed: [string, string, number | null | undefined][] = [
    ["xlogp", "XLogP", props?.pb_computed?.xlogp],
    ["tpsa", t.chemical.knowledge.tpsa, props?.pb_computed?.topological_polar_surface_area],
    ["hbd", t.chemical.knowledge.hbd, props?.pb_computed?.hbond_donor_count],
    ["hba", t.chemical.knowledge.hba, props?.pb_computed?.hbond_acceptor_count],
    ["rotatable", t.chemical.knowledge.rotatable, props?.pb_computed?.rotatable_bond_count],
    ["heavy_atoms", t.chemical.knowledge.heavyAtoms, props?.pb_computed?.heavy_atom_count],
    ["charge", t.chemical.knowledge.charge, props?.pb_computed?.formal_charge],
    ["complexity", t.chemical.knowledge.complexity, props?.pb_computed?.complexity],
  ];
  for (const [key, label, value] of computed) {
    if (value != null) collect(propertyRows, key, label, [formatNumber(value, locale)]);
  }
  for (const row of evidenceRows(props?.pb_physical_properties, locale)) {
    collect(propertyRows, row.label, row.label, row.values);
  }
  for (const row of props?.cb_experimental ?? []) {
    const label = fieldLabel(row.label ?? "", locale);
    // 文本值自带单位与条件（如 "40-42 °C(lit.)"），优先于数值+单位。
    const value = row.text
      ?? [row.v != null ? formatNumber(row.v, locale) : null, row.unit].filter(Boolean).join(" ");
    collect(propertyRows, row.label ?? label, label, [value]);
  }
  const propertyKeys = new Set(propertyRows.map((row) => row.key));

  // ── 安全与法规分区：GHS/危害/防护/毒理/法规证据 + 安全字段，同一字段只出现一次。
  const safetyRows: FieldRow[] = [];
  const PB_SAFETY_BLOCKS = ["ghs_classification", "hazards", "safety_measures", "toxicity", "regulatory"] as const;
  for (const blockKey of PB_SAFETY_BLOCKS) {
    for (const row of evidenceRows(safety?.pb_sections?.[blockKey], locale)) {
      collect(safetyRows, row.label, row.label, row.values);
    }
  }
  for (const [key, value] of Object.entries(safety?.cb_safety ?? {})) {
    collect(safetyRows, key, fieldLabel(key, locale), readableSafetyValues(value, locale));
  }
  const safetyKeys = new Set(safetyRows.map((row) => row.key));

  const showProperties = propertyRows.length > 0 || (props?.cb_prose?.length ?? 0) > 0;
  const showSafety = safetyRows.length > 0
    || (safety?.cb_toxicity?.length ?? 0) > 0 || (safety?.cb_packaging?.length ?? 0) > 0;

  return (
    <div className="pr-root">
      {/* ── Toolbar (screen only, hidden on print) ── */}
      <div className="pr-toolbar no-print">
        <button
          className="pr-btn"
          onClick={undefined}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          suppressHydrationWarning
          // window.print() injected via data-print-btn in a <script> for CSR
          data-print-btn="true"
        >
          {t.print.printAction}
        </button>
        <Link href={withLocale(`/chemical/${id}`, locale)} className="pr-btn pr-btn-ghost">
          {t.print.backAction}
        </Link>
      </div>

      {/* ── Report ── */}
      <article className="pr-page">
        {/* Header */}
        <header className="pr-report-head">
          <div className="pr-logo-row">
            <span className="pr-brand">{t.brand.name}</span>
            <span className="pr-notice">{t.print.reportNotice}</span>
          </div>
          <div className="pr-meta-row">
            <span className="pr-hcid">{t.common.hcidLabel(id)}</span>
            <span className="pr-date">{t.print.generatedAt(printDate)}</span>
          </div>
          <h1 className="pr-title">{title}</h1>
          {aliases.length > 0 && (
            <p className="pr-aliases">{aliases.slice(0, 8).join(" · ")}</p>
          )}
          <p className="pr-url"><a href={pageUrl}>{pageUrl}</a></p>
        </header>

        {/* Structure */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <section className="pr-section pr-structure-section">
          <img
            src={`/api/mol/${id}/png/800x800.png`}
            alt={t.chemical.structureAlt(title)}
            className="pr-structure-img"
            width={400}
            height={400}
          />
        </section>

        {/* Identifiers */}
        {identifierRows.length > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.identifiers}</h2>
            <table className="pr-table">
              <tbody>
                {identifierRows.map(([label, val]) => (
                  <tr key={label}>
                    <th>{label}</th>
                    <td className="pr-mono">{val}</td>
                  </tr>
                ))}
                {cbIdentity.cn && (
                  <tr>
                    <th>{locale === "zh-CN" ? t.chemical.identity.nameCn : t.chemical.identity.localName}</th>
                    <td>{String(cbIdentity.cn)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        )}

        {/* Properties: 每分区一个标题, 分区内按字段组织 */}
        {showProperties && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.properties}</h2>
            <FieldTable rows={propertyRows} />
            <ProseSection items={props?.cb_prose ?? []} skipKeys={propertyKeys} />
          </section>
        )}

        {/* Safety & regulation */}
        {showSafety && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.safety}</h2>
            <FieldTable rows={safetyRows} />
            <ProseSection items={safety?.cb_toxicity ?? []} skipKeys={safetyKeys} />
            <ProseSection items={safety?.cb_packaging ?? []} skipKeys={safetyKeys} />
          </section>
        )}

        {/* Applications */}
        {(industry?.cb_uses?.length ?? 0) > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.applications}</h2>
            <ProseSection items={industry?.cb_uses ?? []} />
          </section>
        )}

        {/* Preparation */}
        {(industry?.cb_preparation?.length ?? 0) > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.synthesis}</h2>
            <ProseSection items={industry?.cb_preparation ?? []} />
          </section>
        )}
      </article>

      {/* Print trigger script */}
      <script
        dangerouslySetInnerHTML={{
          __html: `document.querySelectorAll('[data-print-btn]').forEach(function(b){b.addEventListener('click',function(){window.print();});});`,
        }}
      />
    </div>
  );
}
