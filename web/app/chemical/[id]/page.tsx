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

type DetailResponse = { details: ChemicalDetails | null; enrichment: EnrichmentState };
type SearchParams = { reaction_page?: string; role?: string };

const roles = ["any", "reactant", "product", "reagent", "catalyst", "solvent"] as const;
const roleNames: Record<string, string> = {
  any: "全部", reactant: "作为反应物", product: "作为生成物", reagent: "作为试剂",
  catalyst: "作为催化剂", solvent: "作为溶剂",
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `HCID ${id}`, description: "化合物结构、身份、性质与相关反应" };
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
  const cookie = (await cookies()).toString();
  try {
    chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=full&display=true`, 0, cookie ? { Cookie: cookie } : undefined);
  } catch (error) {
    if (isApiNotFound(error)) notFound();
    throw error;
  }

  let details: DetailResponse = { details: chemical.details || null, enrichment: chemical.enrichment || { status: "current" } };
  let reactions: { total: number; page: number; page_size: number; reactions: ReactionSummary[] } = { total: 0, page, page_size: 8, reactions: [] };
  let reactionsUnavailable = false;
  try { reactions = await apiGet(`/chemicals/${id}/reactions?page=${page}&page_size=8&role=${role}`); } catch { reactionsUnavailable = true; }

  const title = chemical.preferred_name || chemical.iupac_name || details.details?.record_title || "未命名化合物";
  const pageCount = Math.min(500, Math.max(1, Math.ceil(reactions.total / reactions.page_size)));
  const identifiers = identifierGroups(chemical);

  return (
    <div className="content-page chemical-page">
      <nav className="breadcrumbs" aria-label="面包屑"><Link href="/">首页</Link><span>/</span><span>化合物详情</span></nav>
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
            <FollowButton endpoint={`/api/chemicals/${chemical.id}/follow`} initial={Boolean(chemical.is_following)} count={chemical.follower_count || 0} label="收藏" />
            <Link className="button primary" href="#reactions">查看相关反应</Link>
            <Link className="button secondary" href={`/search?chemical_id=${chemical.id}&mode=substructure`}>子结构检索</Link>
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
              {!reactionsUnavailable && <span>{new Intl.NumberFormat("zh-CN").format(reactions.total)} 条</span>}
            </div>
            <div className="role-filter">{roles.map((value) => (
              <Link className={role === value ? "active" : ""} href={`?role=${value}#reactions`} key={value}>{roleNames[value]}</Link>
            ))}</div>
            {reactionsUnavailable ? <p className="quiet-empty">相关反应暂时无法加载，请稍后重试。</p> : reactions.reactions.length > 0 ? (
              <div className="reaction-results">{reactions.reactions.map((reaction) => <ReactionResult reaction={reaction} key={reaction.id} />)}</div>
            ) : <p className="quiet-empty">当前筛选下没有反应记录。</p>}
            {!reactionsUnavailable && pageCount > 1 && <nav className="pagination" aria-label="反应分页">
              {page > 1 && <Link href={`?role=${role}&reaction_page=${page - 1}#reactions`}>上一页</Link>}
              <span>第 {page} / {pageCount} 页</span>
              {page < pageCount && <Link href={`?role=${role}&reaction_page=${page + 1}#reactions`}>下一页</Link>}
            </nav>}
          </section>

        </main>

        <aside className="chemical-aside">
          <section>
            <h2>外部标识</h2>
            <dl>{identifiers.map(([label, values]) => <div key={label}><dt>{label}</dt><dd>{values.join("、")}</dd></div>)}</dl>
          </section>
          <section className="contribute-panel">
            <h2>新建相关反应记录</h2>
            <p>将当前化合物预填为反应物，并自动关联 HCID。</p>
            <Link href={`/submit?chemical=${chemical.id}`}>新建反应记录</Link>
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
