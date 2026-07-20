import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Molecule } from "@/components/Molecule";
import { apiGet, type Chemical, type ReactionSummary } from "@/lib/api";

type HelpPost = { id: number; title: string; body: string; username: string; created_at: string };

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  try {
    const chemical = await apiGet<Chemical>(`/chemicals/${id}`, 3600);
    return { title: chemical.preferred_name || chemical.iupac_name || `化合物 ${id}`, description: chemical.smiles || undefined };
  } catch { return { title: "化合物" }; }
}

export default async function ChemicalPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let chemical: Chemical;
  try { chemical = await apiGet<Chemical>(`/chemicals/${id}`); } catch { notFound(); }
  let reactions: { total: number; reactions: ReactionSummary[] } = { total: 0, reactions: [] };
  let help: HelpPost[] = [];
  try { reactions = await apiGet(`/chemicals/${id}/reactions?page_size=6`); } catch {}
  try { help = await apiGet(`/community/chemicals/${id}/help`); } catch {}
  const identifiers = [
    ...chemical.cas_numbers.map((v) => `CAS ${v}`),
    chemical.pubchem_cid ? `PubChem CID ${chemical.pubchem_cid}` : null,
    chemical.dtxsid,
    chemical.inchikey,
  ].filter(Boolean) as string[];
  return (
    <div className="page narrow">
      <div className="detail-hero">
        <div className="detail-mol"><Molecule smiles={chemical.smiles} width={280} height={230} /></div>
        <div>
          <p className="eyebrow">化合物 #{chemical.id}</p>
          <h1 className="detail-title">{chemical.preferred_name || chemical.iupac_name || "未命名化合物"}</h1>
          {identifiers.slice(0, 5).map((value) => <span className="identifier" key={value}>{value}</span>)}
        </div>
      </div>
      <dl className="facts">
        <Fact label="标准 SMILES" value={chemical.smiles} mono />
        <Fact label="IUPAC" value={chemical.iupac_name} />
        <Fact label="分子式" value={chemical.molecular_formula} />
        <Fact label="平均分子量" value={chemical.average_mass?.toString()} />
        <Fact label="单同位素质量" value={chemical.monoisotopic_mass?.toString()} />
        <Fact label="ChEMBL" value={chemical.chembl_ids.join(", ") || null} />
        <Fact label="ChEBI" value={chemical.chebi_ids.join(", ") || null} />
        <Fact label="UNII" value={chemical.unii_codes.join(", ") || null} />
        <Fact label="EC Number" value={chemical.ec_numbers.join(", ") || null} />
        <Fact label="Nikkaji" value={chemical.nikkaji_numbers.join(", ") || null} />
        <Fact
          label={`别名${chemical.synonym_count ? ` · ${chemical.synonym_count}` : ""}`}
          value={chemical.synonyms?.slice(0, 12).join("、") || null}
        />
      </dl>
      <div className="actions">
        <Link className="button primary" href="#reactions">查看参与反应</Link>
        <Link className="button" href={`/search?chemical_id=${chemical.id}&mode=substructure`}>子结构</Link>
        <Link className="button" href={`/search?chemical_id=${chemical.id}&mode=similarity`}>相似结构</Link>
        <Link className="button" href="/submit?type=reaction">提交相关反应</Link>
      </div>
      {reactions.reactions.length > 0 && (
        <section id="reactions">
          <h2 className="section-label">参与反应 · {reactions.total > 10000 ? "10000+" : reactions.total}</h2>
          <div className="result-list">
            {reactions.reactions.map((reaction) => (
              <Link className="result-row" href={`/reaction/${reaction.id}`} key={reaction.id}>
                <div className="result-sub">#{reaction.id}</div>
                <div><p className="result-title">反应 #{reaction.id}</p><p className="result-sub mono truncate">{reaction.reaction_smiles}</p></div>
                <span className="result-arrow">→</span>
              </Link>
            ))}
          </div>
        </section>
      )}
      {help.length > 0 && (
        <section>
          <h2 className="section-label">反应求助</h2>
          <div className="result-list">
            {help.map((post) => <article className="fact" key={post.id}><strong>{post.title}</strong><p className="prose">{post.body}</p><small className="result-sub">{post.username}</small></article>)}
          </div>
        </section>
      )}
    </div>
  );
}

function Fact({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  if (!value) return null;
  return <div className="fact"><dt>{label}</dt><dd className={mono ? "mono" : ""}>{value}</dd></div>;
}
