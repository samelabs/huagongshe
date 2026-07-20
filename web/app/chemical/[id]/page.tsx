import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ChemicalHelp } from "@/components/ChemicalHelp";
import { ChemicalKnowledge } from "@/components/ChemicalKnowledge";
import { EntityId } from "@/components/EntityId";
import { Molecule } from "@/components/Molecule";
import { ReactionResult } from "@/components/ReactionResult";
import { SynonymExplorer } from "@/components/SynonymExplorer";
import { apiGet, type Chemical, type ChemicalDetails, type EnrichmentState, type ReactionSummary } from "@/lib/api";

type HelpPost = { id: number; title: string; body: string; username: string; created_at: string };
type DetailResponse = { details: ChemicalDetails | null; enrichment: EnrichmentState };
type SearchParams = { reaction_page?: string; role?: string };

const roles = ["any", "reactant", "product", "reagent", "catalyst", "solvent"] as const;
const roleNames: Record<string, string> = {
  any: "全部", reactant: "作为反应物", product: "作为生成物", reagent: "作为试剂",
  catalyst: "作为催化剂", solvent: "作为溶剂",
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  try {
    const chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=full`, 3600);
    return { title: chemical.preferred_name || chemical.iupac_name || `HCID ${id}`, description: chemical.smiles || undefined };
  } catch { return { title: "化合物" }; }
}

export default async function ChemicalPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const page = /^\d+$/.test(query.reaction_page || "") ? Math.max(1, Number(query.reaction_page)) : 1;
  const role = roles.includes(query.role as typeof roles[number]) ? query.role! : "any";
  let chemical: Chemical;
  try { chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=full`); } catch { notFound(); }

  let details: DetailResponse = { details: chemical.details || null, enrichment: chemical.enrichment || { status: "current" } };
  let reactions: { total: number; page: number; page_size: number; reactions: ReactionSummary[] } = { total: 0, page, page_size: 8, reactions: [] };
  let help: HelpPost[] = [];
  try { reactions = await apiGet(`/chemicals/${id}/reactions?page=${page}&page_size=8&role=${role}`); } catch {}
  try { help = await apiGet(`/community/chemicals/${id}/help`); } catch {}

  const title = chemical.preferred_name || chemical.iupac_name || details.details?.record_title || "未命名化合物";
  const pageCount = Math.min(500, Math.max(1, Math.ceil(reactions.total / reactions.page_size)));
  const identifiers = identifierGroups(chemical);

  return (
    <div className="content-page chemical-page">
      <nav className="breadcrumbs" aria-label="面包屑"><Link href="/">首页</Link><span>/</span><EntityId kind="chemical" id={chemical.id} compact /></nav>
      <header className="chemical-identity">
        <div className="chemical-structure"><Molecule smiles={chemical.smiles} width={360} height={280} /></div>
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
            <Link className="button primary" href="#reactions">查看参与反应</Link>
            <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=substructure`}>查找子结构</Link>
            <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=similarity`}>查找相似结构</Link>
          </div>
        </div>
      </header>

      <div className="chemical-layout">
        <main className="chemical-main">
          <section className="identity-section">
            <div className="section-heading compact-heading"><div><p>IDENTITY</p><h2>结构与身份</h2></div></div>
            <dl className="identity-table">
              <Identity label="标准 SMILES" value={chemical.smiles} mono />
              <Identity label="InChIKey" value={chemical.inchikey} mono />
              <Identity label="分子式" value={chemical.molecular_formula} />
              <Identity label="平均分子量" value={chemical.average_mass != null ? `${formatNumber(chemical.average_mass)} g/mol` : null} />
              <Identity label="单同位素质量" value={chemical.monoisotopic_mass != null ? formatNumber(chemical.monoisotopic_mass, 8) : null} />
            </dl>
          </section>

          <ChemicalKnowledge details={details.details} enrichment={details.enrichment} />
          <SynonymExplorer chemicalId={chemical.id} initial={chemical.synonyms || []} total={chemical.synonym_count || 0} />

          <section className="chemical-reactions" id="reactions">
            <div className="section-heading">
              <div><p>REACTIONS</p><h2>参与反应</h2></div>
              <span>{new Intl.NumberFormat("zh-CN").format(reactions.total)} 条</span>
            </div>
            <div className="role-filter">{roles.map((value) => (
              <Link className={role === value ? "active" : ""} href={`?role=${value}#reactions`} key={value}>{roleNames[value]}</Link>
            ))}</div>
            {reactions.reactions.length > 0 ? (
              <div className="reaction-results">{reactions.reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
            ) : <p className="quiet-empty">当前筛选下没有反应记录。</p>}
            {pageCount > 1 && <nav className="pagination" aria-label="反应分页">
              {page > 1 && <Link href={`?role=${role}&reaction_page=${page - 1}#reactions`}>上一页</Link>}
              <span>第 {page} / {pageCount} 页</span>
              {page < pageCount && <Link href={`?role=${role}&reaction_page=${page + 1}#reactions`}>下一页</Link>}
            </nav>}
          </section>

          <ChemicalHelp chemicalId={chemical.id} initialPosts={help} />
        </main>

        <aside className="chemical-aside">
          <section>
            <h2>外部标识</h2>
            <dl>{identifiers.map(([label, values]) => <div key={label}><dt>{label}</dt><dd>{values.join("、")}</dd></div>)}</dl>
          </section>
          <section className="contribute-panel">
            <h2>维护这条数据</h2>
            <p>核心结构和身份的变更需要结构校验与人工审核。</p>
            <Link href={`/submit?type=chemical&chemical=${chemical.id}`}>补充或纠正化合物</Link>
            <Link href={`/submit?type=reaction&chemical=${chemical.id}`}>提交相关反应</Link>
            <Link href="#reaction-help">发布反应求助</Link>
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
