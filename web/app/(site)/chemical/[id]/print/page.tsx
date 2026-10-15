import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { apiGet, isApiGone, isEntityId, type Chemical, type SemanticDetail, type ProseItem, type EvidenceBlock } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import "./print.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

function formatNumber(n: number | null | undefined, locale: string, fractionDigits = 4): string {
  if (n == null) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: fractionDigits }).format(n);
}

function ProseSection({ title, items }: { title: string; items: ProseItem[] }) {
  if (!items.length) return null;
  return (
    <section className="pr-section">
      <h2 className="pr-section-h">{title}</h2>
      {items.map((item, i) => (
        <div key={i} className="pr-prose-item">
          {item.title && <h3 className="pr-prose-title">{item.title}</h3>}
          <p className="pr-prose-text">{item.text}</p>
        </div>
      ))}
    </section>
  );
}

/** CB safety 字段的值可能是字符串或嵌套对象(GHS 的 h/p/象形图/信号词):
 *  报告里渲染成 "键: 值" 逗号串, 不打印 [object Object]。 */
function readableSafetyValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(readableSafetyValue).filter(Boolean).join("、");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${readableSafetyValue(v)}`)
      .join("；");
  }
  return String(value);
}

function EvidenceSection({ title, block }: { title: string; block: EvidenceBlock | null | undefined }) {  if (!block || !block.entries || Object.keys(block.entries).length === 0) return null;
  const entries = block.entries as Record<string, { value?: string; text?: string; unit?: string }>;
  return (
    <section className="pr-section">
      <h2 className="pr-section-h">{title}</h2>
      <table className="pr-table">
        <tbody>
          {Object.entries(entries).map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{v?.value ?? v?.text ?? "—"}{v?.unit ? ` ${v.unit}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default async function ChemicalPrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isEntityId(id)) notFound();

  const locale = await getRequestLocale();
  const t = await getRequestDictionary();

  // 语义详情与主记录同源: /chemicals/{id}?enrich=full 的 details 字段
  // (站点没有独立的 /details 路由)。
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

        {/* Computed Properties */}
        {props?.pb_computed && Object.keys(props.pb_computed).length > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.properties}</h2>
            <table className="pr-table">
              <tbody>
                {[
                  ["XLogP", props.pb_computed.xlogp],
                  [t.chemical.knowledge.tpsa, props.pb_computed.topological_polar_surface_area],
                  [t.chemical.knowledge.hbd, props.pb_computed.hbond_donor_count],
                  [t.chemical.knowledge.hba, props.pb_computed.hbond_acceptor_count],
                  [t.chemical.knowledge.rotatable, props.pb_computed.rotatable_bond_count],
                  [t.chemical.knowledge.heavyAtoms, props.pb_computed.heavy_atom_count],
                  [t.chemical.knowledge.charge, props.pb_computed.formal_charge],
                  [t.chemical.knowledge.complexity, props.pb_computed.complexity],
                ].filter(([, v]) => v != null).map(([label, val]) => (
                  <tr key={String(label)}>
                    <th>{label}</th>
                    <td>{formatNumber(val as number, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <EvidenceSection title={t.print.properties} block={props?.pb_physical_properties} />

        {/* CB Experimental */}
        {(props?.cb_experimental?.length ?? 0) > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.properties}</h2>
            <table className="pr-table">
              <tbody>
                {(props!.cb_experimental ?? []).map((row, i) => (
                  <tr key={i}>
                    <th>{row.label ?? "—"}</th>
                    <td>{[row.v != null ? formatNumber(row.v, locale) : null, row.unit].filter(Boolean).join(" ") || row.text || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <ProseSection title={t.print.properties} items={props?.cb_prose ?? []} />

        {/* Safety */}
        <EvidenceSection title={t.print.safety} block={safety?.pb_sections?.["Safety and Hazards"]} />
        {safety?.cb_safety && Object.keys(safety.cb_safety).length > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.safety}</h2>
            <table className="pr-table">
              <tbody>
                {Object.entries(safety.cb_safety).map(([k, v]) => (
                  <tr key={k}><th>{k}</th><td>{readableSafetyValue(v)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
        <ProseSection title={t.print.safety} items={safety?.cb_toxicity ?? []} />
        <ProseSection title={t.print.safety} items={safety?.cb_packaging ?? []} />

        {/* Applications */}
        <ProseSection title={t.print.applications} items={industry?.cb_uses ?? []} />

        {/* Preparation */}
        <ProseSection title={t.print.synthesis} items={industry?.cb_preparation ?? []} />
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
