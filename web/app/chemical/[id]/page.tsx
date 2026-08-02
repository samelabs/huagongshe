import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ChemicalKnowledge } from "@/components/ChemicalKnowledge";
import { EntityId } from "@/components/EntityId";
import { FollowButton } from "@/components/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionResult } from "@/components/ReactionResult";
import { SynonymExplorer } from "@/components/SynonymExplorer";
import { apiGet, isApiNotFound, type Chemical, type ChemicalDetails, type EnrichmentState, type ReactionSummary } from "@/lib/api";
import t from "@/lib/i18n";

type DetailResponse = { details: ChemicalDetails | null; enrichment: EnrichmentState };
type SearchParams = { reaction_page?: string; role?: string };

// Anonymous traffic gets ISR (1h). Logged-in users skip the cache for live
// follow state and enrichment queue feedback.
export const revalidate = 3600;

const roles = ["any", "reactant", "product", "reagent", "catalyst", "solvent"] as const;
const roleNames: Record<string, string> = {
  any: t.common.all, reactant: t.chemical.roles.reactant, product: t.chemical.roles.product, reagent: t.chemical.roles.reagent,
  catalyst: t.chemical.roles.catalyst, solvent: t.chemical.roles.solvent,
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `HCID ${id}`, description: t.chemical.desc };
}

export default async function ChemicalPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const page = /^\d+$/.test(query.reaction_page || "") ? Math.max(1, Number(query.reaction_page)) : 1;
  const role = roles.includes(query.role as typeof roles[number]) ? query.role! : "any";
  // Logged-in users get dynamic rendering for live follow state and
  // enrichment queue feedback; anonymous traffic hits the ISR cache.
  const hasSession = (await cookies()).has("hgs_session");
  const ttl = hasSession ? 0 : 3600;
  const authHeaders = hasSession ? { Cookie: (await cookies()).toString() } : undefined;

  // These two requests have no dependency on each other — reactions only needs
  // the chemical ID from the URL, not from the detail response. Fire them in
  // parallel to cut SSR time, then split the results.
  const [chemicalResult, reactionsResult] = await Promise.all([
    apiGet<Chemical>(`/chemicals/${id}?enrich=full&display=true`, ttl, authHeaders).catch((error: unknown) => {
      if (isApiNotFound(error)) notFound();
      throw error;
    }),
    apiGet<{ total: number; page: number; page_size: number; reactions: ReactionSummary[] }>(
      `/chemicals/${id}/reactions?page=${page}&page_size=8&role=${role}`, ttl, authHeaders,
    ).catch(() => null),
  ]);
  const chemical = chemicalResult;
  const reactionsUnavailable = reactionsResult === null;
  const reactions = reactionsResult ?? { total: 0, page, page_size: 8, reactions: [] as ReactionSummary[] };

  const details: DetailResponse = { details: chemical.details || null, enrichment: chemical.enrichment || { status: "current" } };

  const title = chemical.preferred_name || chemical.iupac_name || details.details?.record_title || t.common.unnamedCompound;
  const pageCount = Math.min(500, Math.max(1, Math.ceil(reactions.total / reactions.page_size)));
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
            {hasSession ? (
              <>
                <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=substructure`}>{t.chemical.substructure}</Link>
                <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=similarity`}>{t.chemical.similarity}</Link>
              </>
            ) : (
              <Link className="button secondary" href="/login?next=%2Fchemical%3F">{t.chemical.structureLogin}</Link>
            )}
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
              {!reactionsUnavailable && <span>{new Intl.NumberFormat("zh-CN").format(reactions.total)} 条</span>}
            </div>
            <div className="role-filter">{roles.map((value) => (
              <Link className={role === value ? "active" : ""} href={`?role=${value}#reactions`} key={value}>{roleNames[value]}</Link>
            ))}</div>
            {reactionsUnavailable ? <p className="quiet-empty">{t.chemical.errReactions}</p> : reactions.reactions.length > 0 ? (
              <div className="reaction-results">{reactions.reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
            ) : <p className="quiet-empty">{t.chemical.noReactions}</p>}
            {!reactionsUnavailable && pageCount > 1 && <nav className="pagination" aria-label={t.common.pageNav}>
              {page > 1 && <Link href={`?role=${role}&reaction_page=${page - 1}#reactions`}>{t.common.prev}</Link>}
              <span>{t.common.pageOf(page, pageCount)}</span>
              {page < pageCount && <Link href={`?role=${role}&reaction_page=${page + 1}#reactions`}>{t.common.next}</Link>}
            </nav>}
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
