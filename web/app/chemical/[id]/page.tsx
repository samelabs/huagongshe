import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ChemicalKnowledge } from "@/components/ChemicalKnowledge";
import { EntityId } from "@/components/EntityId";
import { FollowButton } from "@/components/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionList } from "@/components/ReactionList";
import { SynonymExplorer } from "@/components/SynonymExplorer";
import { apiGet, isApiNotFound, type Chemical, type ChemicalDetails, type EnrichmentState, type ReactionSummary } from "@/lib/api";
import t from "@/lib/i18n";

type DetailResponse = { details: ChemicalDetails | null; enrichment: EnrichmentState };

// Anonymous traffic gets ISR (1h). Logged-in users skip the cache for live
// follow state and enrichment queue feedback.
export const revalidate = 3600;

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `HCID ${id}`, description: t.chemical.desc };
}

export default async function ChemicalPage({ params }: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const ttl = 3600;

  const [chemicalResult, reactionsResult] = await Promise.all([
    apiGet<Chemical>(`/chemicals/${id}?enrich=full&display=true`, ttl).catch((error: unknown) => {
      if (isApiNotFound(error)) notFound();
      throw error;
    }),
    apiGet<{ total: number; page: number; page_size: number; reactions: ReactionSummary[] }>(
      `/chemicals/${id}/reactions?page=1&page_size=8&role=any`, ttl,
    ).catch(() => null),
  ]);
  const chemical = chemicalResult;
  const reactionsUnavailable = reactionsResult === null;
  const initialReactions = reactionsResult?.reactions ?? [];
  const reactionTotal = reactionsResult?.total ?? 0;

  const details: DetailResponse = { details: chemical.details || null, enrichment: chemical.enrichment || { status: "current" } };

  const title = chemical.preferred_name || chemical.iupac_name || details.details?.record_title || t.common.unnamedCompound;
  const identifiers = identifierGroups(chemical);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "MolecularEntity",
    name: title,
    ...(chemical.iupac_name ? { iupacName: chemical.iupac_name } : {}),
    ...(chemical.molecular_formula ? { molecularFormula: chemical.molecular_formula } : {}),
    ...(chemical.molecular_formula ? { molecularWeight: chemical.average_mass ? String(chemical.average_mass) : undefined } : {}),
    ...(chemical.smiles ? { smiles: chemical.smiles } : {}),
    ...(chemical.inchikey ? { inChIKey: chemical.inchikey } : {}),
    ...(chemical.cas_numbers.length ? { casNumber: chemical.cas_numbers[0] } : {}),
    ...(chemical.pubchem_cid ? { url: `https://huagongshe.com/chemical/${chemical.id}` } : {}),
  };

  return (
    <div className="content-page chemical-page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <nav className="breadcrumbs" aria-label={t.common.breadcrumb}><Link href="/">{t.chemical.home}</Link><span>/</span><span>{t.chemical.detail}</span></nav>
      <header className="chemical-identity">
        <div className="chemical-structure"><Molecule chemicalId={chemical.id} label={chemical.preferred_name || chemical.iupac_name} width={360} height={280} /></div>
        <div className="chemical-title-block">
          <EntityId kind="chemical" id={chemical.id} />
          <h1>{title}</h1>
          {chemical.iupac_name && chemical.iupac_name.toLowerCase() !== title.toLowerCase() && <p className="iupac-name">{chemical.iupac_name}</p>}
          <div className="identity-primary">
            {chemical.molecular_formula && <span>{chemical.molecular_formula}</span>}
            {chemical.average_mass != null && <span>{formatNumber(chemical.average_mass)} g/mol</span>}
            {chemical.cas_numbers[0] && <span>CAS {chemical.cas_numbers[0]}</span>}
          </div>
          <div className="context-actions">
            <FollowButton endpoint={`/api/chemicals/${chemical.id}/follow`} initial={Boolean(chemical.is_following)} count={chemical.follower_count || 0} label={t.chemical.favor} />
            <Link className="button primary" href="#reactions">{t.chemical.viewReactions}</Link>
            <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=substructure`}>{t.chemical.substructure}</Link>
            <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=similarity`}>{t.chemical.similarity}</Link>
          </div>
        </div>
      </header>

      <div className="chemical-layout">
        <main className="chemical-main">
          <section className="identity-section">
            <div className="section-heading compact-heading"><div><p>IDENTITY</p><h2>{t.chemical.structureIdentity}</h2></div></div>
            <dl className="identity-table">
              <Identity label={t.chemical.identity.standardSmiles} value={chemical.smiles} mono />
              <Identity label="InChIKey" value={chemical.inchikey} mono />
              <Identity label={t.chemical.identity.formula} value={chemical.molecular_formula} />
              <Identity label={t.chemical.identity.avgMass} value={chemical.average_mass != null ? `${formatNumber(chemical.average_mass)} g/mol` : null} />
              <Identity label={t.chemical.identity.monoMass} value={chemical.monoisotopic_mass != null ? formatNumber(chemical.monoisotopic_mass, 8) : null} />
            </dl>
          </section>

          <ChemicalKnowledge details={details.details} enrichment={details.enrichment} />
          <SynonymExplorer chemicalId={chemical.id} initial={chemical.synonyms || []} total={chemical.synonym_count || 0} />

          <section className="chemical-reactions" id="reactions">
            <div className="section-heading">
              <div><p>REACTIONS</p><h2>{t.chemical.relatedReactions}</h2></div>
              {!reactionsUnavailable && <span>{new Intl.NumberFormat("zh-CN").format(reactionTotal)} 条</span>}
            </div>
            {reactionsUnavailable ? <p className="quiet-empty">{t.chemical.errReactions}</p> : <ReactionList chemicalId={chemical.id} initial={initialReactions} />}
          </section>

        </main>

        <aside className="chemical-aside">
          <section>
            <h2>{t.chemical.external}</h2>
            <dl>{identifiers.map(([label, values]) => <div key={label}><dt>{label}</dt><dd>{values.join("、")}</dd></div>)}</dl>
          </section>
          <section className="contribute-panel">
            <h2>{t.chemical.newRelated}</h2>
            <p>{t.chemical.newRelatedHint}</p>
            <Link href={`/submit?chemical=${chemical.id}`}>{t.chemical.newReaction}</Link>
          </section>
        </aside>
      </div>
    </div>
  );
}

function Identity({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd className={mono ? "mono" : ""}>{value}</dd></div>;
}

function formatNumber(value: number, digits = 4) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(value);
}

function identifierGroups(chemical: Chemical): [string, string[]][] {
  return [
    ["CAS", chemical.cas_numbers],
    ["PubChem CID", chemical.pubchem_cid ? [String(chemical.pubchem_cid)] : []],
    ["DTXSID", chemical.dtxsid ? [chemical.dtxsid] : []],
    ["ChEMBL", chemical.chembl_ids],
    ["ChEBI", chemical.chebi_ids],
    ["UNII", chemical.unii_codes],
    ["EC Number", chemical.ec_numbers],
    ["Nikkaji", chemical.nikkaji_numbers],
  ].filter((entry): entry is [string, string[]] => entry[1].length > 0);
}
