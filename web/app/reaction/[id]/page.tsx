import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Molecule } from "@/components/Molecule";
import { apiGet, type Chemical, type ReactionDetail } from "@/lib/api";

const roleNames: Record<string, string> = {
  REACTANT: "反应物", REAGENT: "试剂", CATALYST: "催化剂", SOLVENT: "溶剂",
  PRODUCT: "生成物", WORKUP: "后处理", INTERNAL_STANDARD: "内标", UNKNOWN: "其他",
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `反应 #${id}`, description: "反应方程式、反应物、生成物与实验信息" };
}

export default async function ReactionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let reaction: ReactionDetail;
  try { reaction = await apiGet<ReactionDetail>(`/reactions/${id}`); } catch { notFound(); }

  const reactants = reaction.participants.filter((item) => item.role === "REACTANT");
  const products = reaction.participants.filter((item) => item.role === "PRODUCT");
  const auxiliaries = reaction.participants.filter((item) => item.role !== "REACTANT" && item.role !== "PRODUCT");

  return (
    <div className="page reaction-page">
      <div className="page-head">
        <p className="eyebrow">反应记录</p>
        <h1>反应 #{reaction.id}</h1>
      </div>

      <section aria-labelledby="reaction-equation-title">
        <h2 className="section-label" id="reaction-equation-title">反应方程式</h2>
        <div className="reaction-scheme">
          <img
            src={`/api/reactions/${reaction.id}/svg?w=1400&h=320`}
            width="1400"
            height="320"
            alt={`反应 ${reaction.id} 的结构方程式`}
          />
        </div>
        <details className="reaction-source-expression">
          <summary>查看反应 SMILES</summary>
          <div className="reaction-code mono">{reaction.reaction_smiles}</div>
        </details>
      </section>

      <div className="reaction-groups">
        <ParticipantGroup title="反应物" items={reactants} />
        <ParticipantGroup title="生成物" items={products} />
        {auxiliaries.length > 0 && <ParticipantGroup title="试剂与条件组分" items={auxiliaries} showRole />}
      </div>

      <dl className="facts">
        {reaction.temperature && <Fact label="温度" value={`${reaction.temperature.value} ${reaction.temperature.unit}`} />}
        {reaction.ph != null && <Fact label="pH" value={String(reaction.ph)} />}
        {reaction.reflux && <Fact label="回流" value="是" />}
        <Fact label="条件" value={reaction.conditions_detail} />
        <Fact label="DOI" value={reaction.doi} />
        <Fact label="专利" value={reaction.patent} />
        <Fact label="数据来源" value={reaction.ord_id ? "Open Reaction Database (ORD)" : null} />
        <Fact label="来源数据集" value={reaction.dataset_name} />
        <Fact label="来源记录" value={reaction.ord_id} />
      </dl>
      {reaction.procedure_details && <section><h2 className="section-label">实验过程</h2><p className="prose">{reaction.procedure_details}</p></section>}
      {reaction.workup.length > 0 && <section><h2 className="section-label">后处理</h2>{reaction.workup.map((step, index) => <p className="prose" key={index}>{index + 1}. {step.type ? `${step.type} · ` : ""}{step.details}</p>)}</section>}
      {reaction.safety_notes && <section><h2 className="section-label">安全说明</h2><p className="prose">{reaction.safety_notes}</p></section>}
      <div className="actions"><Link className="button" href={`/submit?type=reaction&reaction=${reaction.id}`}>补充或纠正该反应</Link></div>
    </div>
  );
}

function ParticipantGroup({
  title,
  items,
  showRole = false,
}: {
  title: string;
  items: Chemical[];
  showRole?: boolean;
}) {
  return (
    <section className="reaction-group">
      <div className="reaction-group-head">
        <h2>{title}</h2>
        <span>{items.length}</span>
      </div>
      {items.length > 0 ? (
        <div className="participants">
          {items.map((chemical) => (
            <Link className="participant" href={`/chemical/${chemical.id}`} key={`${chemical.role}-${chemical.id}`}>
              {showRole && <span className="participant-role">{roleNames[chemical.role || ""] || chemical.role}</span>}
              <div className="mol-frame"><Molecule smiles={chemical.smiles} width={210} height={130} /></div>
              <p className="result-title">{chemical.preferred_name || chemical.iupac_name || `化合物 #${chemical.id}`}</p>
              {chemical.molecular_formula && <p className="result-sub">{chemical.molecular_formula}</p>}
              {chemical.yield_percent != null && <p className="participant-yield">收率 {formatYield(chemical.yield_percent)}%</p>}
            </Link>
          ))}
        </div>
      ) : <p className="reaction-group-empty">暂无可识别的{title}</p>}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return <div className="fact"><dt>{label}</dt><dd>{value}</dd></div>;
}

function formatYield(value: number) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(value);
}
