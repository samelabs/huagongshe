import Link from "next/link";
import { Molecule } from "@/components/Molecule";
import type { Chemical } from "@/lib/api";

export function ChemicalResult({ chemical }: { chemical: Chemical }) {
  const title = chemical.preferred_name || chemical.iupac_name || `化合物 ${chemical.id}`;
  const identity = [
    chemical.cas_numbers[0] ? `CAS ${chemical.cas_numbers[0]}` : null,
    chemical.pubchem_cid ? `CID ${chemical.pubchem_cid}` : null,
    chemical.molecular_formula,
  ].filter(Boolean).join(" · ");

  return (
    <article className="chemical-result">
      <Link className="chemical-result-structure" href={`/chemical/${chemical.id}`} aria-label={`查看 ${title}`}>
        <Molecule smiles={chemical.smiles} width={176} height={122} />
      </Link>
      <div className="chemical-result-copy">
        <p className="record-kicker">化合物 {chemical.id}</p>
        <h3><Link href={`/chemical/${chemical.id}`}>{title}</Link></h3>
        {identity && <p className="record-meta">{identity}</p>}
        {chemical.smiles && <p className="structure-code mono">{chemical.smiles}</p>}
        {chemical.similarity != null && <p className="match-score">结构相似度 {(chemical.similarity * 100).toFixed(1)}%</p>}
      </div>
      <Link className="record-open" href={`/chemical/${chemical.id}`}>查看</Link>
    </article>
  );
}
