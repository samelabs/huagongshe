import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { Molecule } from "@/components/Molecule";
import type { Chemical } from "@/lib/api";
import t from "@/lib/i18n";

export function ChemicalResult({ chemical }: { chemical: Chemical }) {
  const title = chemical.preferred_name || chemical.iupac_name || t.common.unnamedCompound;
  const identity = [
    chemical.cas_numbers[0] ? `CAS ${chemical.cas_numbers[0]}` : null,
    chemical.pubchem_cid ? `CID ${chemical.pubchem_cid}` : null,
    chemical.molecular_formula,
  ].filter(Boolean).join(" · ");

  return (
    <article className="chemical-result">
      <Link className="chemical-result-structure" href={`/chemical/${chemical.id}`} aria-label={`${t.common.view} ${title}`}>
        <Molecule chemicalId={chemical.id} label={chemical.preferred_name || chemical.iupac_name} width={176} height={122} />
      </Link>
      <div className="chemical-result-copy">
        <EntityId kind="chemical" id={chemical.id} compact />
        <h3><Link href={`/chemical/${chemical.id}`}>{title}</Link></h3>
        {identity && <p className="record-meta">{identity}</p>}
        {chemical.smiles && <p className="structure-code mono">{chemical.smiles}</p>}
        {chemical.similarity != null && <p className="match-score">{t.search.similarityScore(chemical.similarity * 100)}</p>}
      </div>
      <Link className="record-open" href={`/chemical/${chemical.id}`}>{t.common.view}</Link>
    </article>
  );
}
