import type { ChemicalDetails, EnrichmentState, EvidenceBlock } from "@/lib/api";
import t from "@/lib/i18n";

const sections: { key: keyof ChemicalDetails; eyebrow: string; title: string }[] = [
  { key: "physical_properties", eyebrow: "PROPERTIES", title: t.chemical.knowledge.experimental },
  { key: "ghs_classification", eyebrow: "GHS", title: t.chemical.knowledge.ghs },
  { key: "hazards", eyebrow: "HAZARDS", title: t.chemical.knowledge.hazards },
  { key: "safety_measures", eyebrow: "SAFETY", title: t.chemical.knowledge.safety },
  { key: "toxicity", eyebrow: "TOXICITY", title: t.chemical.knowledge.toxicology },
  { key: "regulatory", eyebrow: "REGULATORY", title: t.chemical.knowledge.regulatory },
  { key: "pharmacology", eyebrow: "PHARMACOLOGY", title: t.chemical.knowledge.pharmacology },
  { key: "uses_and_manufacturing", eyebrow: "USES", title: t.chemical.knowledge.uses },
];

export function ChemicalKnowledge({ details, enrichment }: {
  details: ChemicalDetails | null | undefined;
  enrichment: EnrichmentState | null | undefined;
}) {
  if (!details) {
    return <div className="enrichment-note">{t.chemical.knowledge.enrichError}</div>;
  }
  const available = sections.filter(({ key }) => hasEntries(details[key]));
  return (
    <>
      {details.record_description && <section className="description-panel"><p>{details.record_description}</p></section>}
      <section className="computed-section">
        <div className="section-heading compact-heading"><div><p>COMPUTED</p><h2>{t.chemical.knowledge.descriptors}</h2></div><SourceState enrichment={enrichment} /></div>
        <dl className="metric-grid">
          <Metric label="XLogP" value={details.xlogp} />
          <Metric label={t.chemical.knowledge.tpsa} value={details.topological_polar_surface_area} suffix=" Å²" />
          <Metric label={t.chemical.knowledge.hbd} value={details.hbond_donor_count} />
          <Metric label={t.chemical.knowledge.hba} value={details.hbond_acceptor_count} />
          <Metric label={t.chemical.knowledge.rotatable} value={details.rotatable_bond_count} />
          <Metric label={t.chemical.knowledge.heavyAtoms} value={details.heavy_atom_count} />
          <Metric label={t.chemical.knowledge.charge} value={details.formal_charge} />
          <Metric label={t.chemical.knowledge.complexity} value={details.complexity} />
        </dl>
      </section>
      {available.map(({ key, eyebrow, title }) => (
        <EvidenceSection key={key} eyebrow={eyebrow} title={title} block={details[key] as EvidenceBlock} />
      ))}
      {available.length === 0 && enrichment?.status !== "current" && (
        <div className="enrichment-note">{t.chemical.knowledge.enriching}</div>
      )}
    </>
  );
}

function SourceState({ enrichment }: { enrichment?: EnrichmentState | null }) {
  if (!enrichment || enrichment.status === "current") return null;
  return <span>{t.chemical.knowledge.enriching}</span>;
}

function Metric({ label, value, suffix = "" }: { label: string; value: number | null | undefined; suffix?: string }) {
  if (value == null) return null;
  return <div><dt>{label}</dt><dd>{new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(value)}{suffix}</dd></div>;
}

function hasEntries(value: unknown) {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  const entries = record.entries && typeof record.entries === "object" ? record.entries as Record<string, unknown> : record;
  return Object.keys(entries).some((key) => !["references", "normalization"].includes(key));
}

function EvidenceSection({ eyebrow, title, block }: { eyebrow: string; title: string; block: EvidenceBlock }) {
  const source = block.entries && typeof block.entries === "object" ? block.entries : block;
  const entries = Object.entries(source).filter(([key]) => !["references", "normalization"].includes(key)).slice(0, 12);
  if (!entries.length) return null;
  return (
    <section className="evidence-section">
      <div className="section-heading compact-heading"><div><p>{eyebrow}</p><h2>{title}</h2></div></div>
      <div className="evidence-list">{entries.map(([path, values], index) => (
        <details key={`${path}-${index}`} open={index < 3}>
          <summary>{leafLabel(path)}</summary>
          <div>{displayValues(values).map((value, valueIndex) => <p key={valueIndex}>{value}</p>)}</div>
        </details>
      ))}</div>
    </section>
  );
}

function leafLabel(path: string) {
  return path.split(" > ").at(-1) || path;
}

function displayValues(input: unknown): string[] {
  const list = Array.isArray(input) ? input : [input];
  const result: string[] = [];
  for (const item of list.slice(0, 6)) {
    if (item == null) continue;
    if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
      result.push(String(item)); continue;
    }
    if (typeof item === "object") {
      const record = item as Record<string, unknown>;
      const raw = record.value ?? record.name ?? record.description ?? record.text;
      if (Array.isArray(raw)) result.push(raw.map((value) => scalar(value)).filter(Boolean).join("；"));
      else if (raw != null) result.push(scalar(raw));
    }
  }
  return result.filter(Boolean).slice(0, 6);
}

function scalar(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.StringWithMarkup && Array.isArray(record.StringWithMarkup)) {
      return record.StringWithMarkup.map((item) => scalar((item as Record<string, unknown>)?.String)).filter(Boolean).join(" ");
    }
  }
  return "";
}
