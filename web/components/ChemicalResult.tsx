import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { Molecule } from "@/components/Molecule";
import type { Chemical } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

export async function ChemicalResult({ chemical }: { chemical: Chemical }) {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  // 名称解析唯一出口(与详情页/SEO 同规则): 本地化名 → 英文常用名 → 系统名 → 分子式 → HCID
  const { title, secondary } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  const identity = [
    secondary,
    chemical.cas_numbers[0] ? `CAS ${chemical.cas_numbers[0]}` : null,
    chemical.pubchem_cid ? `CID ${chemical.pubchem_cid}` : null,
    chemical.molecular_formula,
  ].filter(Boolean).join(" · ");
  const href = withLocale(`/chemical/${chemical.id}`, locale);

  return (
    <article className="chemical-result">
      <Link className="chemical-result-structure" href={href} aria-label={`${t.common.view} ${title}`}>
        <Molecule
          chemicalId={chemical.id}
          label={title}
          width={176}
          height={122}
          alt={t.chemical.structureAlt(title)}
          noStructureText={t.reaction.noStructure}
        />
      </Link>
      <div className="chemical-result-copy">
        <EntityId kind="chemical" id={chemical.id} compact ariaLabel={t.common.hcidLabel(chemical.id)} />
        <h3><Link href={href}>{title}</Link></h3>
        {identity && <p className="record-meta">{identity}</p>}
        {chemical.smiles && <p className="structure-code mono">{chemical.smiles}</p>}
        {chemical.similarity != null && <p className="match-score">{t.search.similarityScore(chemical.similarity * 100)}</p>}
      </div>
      <Link className="record-open" href={href}>{t.common.view}</Link>
    </article>
  );
}
