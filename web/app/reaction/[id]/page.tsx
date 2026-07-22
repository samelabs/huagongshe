import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { EntityId } from "@/components/EntityId";
import { FollowButton } from "@/components/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionOwnerActions } from "@/components/ReactionOwnerActions";
import { apiGet, isApiNotFound, reactionSvgUrl, type Chemical, type ReactionDetail } from "@/lib/api";

const roleNames: Record<string, string> = {
  REACTANT: "反应物", REAGENT: "试剂", CATALYST: "催化剂", SOLVENT: "溶剂",
  PRODUCT: "生成物", WORKUP: "后处理", INTERNAL_STANDARD: "内标", UNKNOWN: "其他",
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `HRID ${id}`, description: "反应方程式、参与物、条件、结果与来源" };
}

export default async function ReactionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let reaction: ReactionDetail;
  const cookie = (await cookies()).toString();
  try { reaction = await apiGet<ReactionDetail>(`/reactions/${id}`, 0, cookie ? { Cookie: cookie } : undefined); }
  catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  const reactants = reaction.participants.filter((item) => item.role === "REACTANT");
  const products = reaction.participants.filter((item) => item.role === "PRODUCT");
  const auxiliaries = reaction.participants.filter((item) => item.role !== "REACTANT" && item.role !== "PRODUCT");
  const conditions = [
    reaction.temperature ? ["温度", `${reaction.temperature.value} ${unitName(reaction.temperature.unit)}`] : null,
    reaction.duration ? ["时间", `${reaction.duration.value} ${unitName(reaction.duration.unit)}`] : null,
    reaction.atmosphere ? ["气氛", reaction.atmosphere] : null,
    reaction.pressure ? ["压力", `${reaction.pressure.value} ${reaction.pressure.unit}`] : null,
    reaction.ph != null ? ["pH", String(reaction.ph)] : null,
    reaction.reflux ? ["回流", "是"] : null,
  ].filter(Boolean) as string[][];

  return (
    <div className="content-page reaction-page">
      <nav className="breadcrumbs" aria-label="面包屑"><Link href={reaction.is_owner ? "/me" : "/"}>{reaction.is_owner ? "我的反应" : "查数据"}</Link><span>/</span><span>反应详情</span></nav>
      <header className="reaction-title">
        <div>
          <EntityId kind="reaction" id={reaction.id} />
          <h1>反应详情</h1>
        </div>
        {reaction.is_owner ? <ReactionOwnerActions reactionId={reaction.id} /> : <FollowButton endpoint={`/api/reactions/${reaction.id}/follow`} initial={reaction.is_following} count={reaction.follower_count} label="收藏" />}
      </header>

      <section className="reaction-equation" aria-labelledby="equation-title">
        <div className="section-heading compact-heading"><div><p>EQUATION</p><h2 id="equation-title">反应方程式</h2></div></div>
        {reaction.reaction_smiles ? <div className="reaction-scheme">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(reaction.id, 1500, 340)} width="1500" height="340" alt={`HRID ${reaction.id} 的结构方程式`} />
        </div> : <div className="reaction-scheme unavailable">反应物或生成物不完整，无法生成方程式</div>}
      </section>

      <div className="reaction-layout">
        <main className="reaction-main">
          <div className="reaction-sides">
            <ParticipantGroup title="反应物" eyebrow="REACTANTS" items={reactants} />
            <ParticipantGroup title="生成物" eyebrow="PRODUCTS" items={products} />
          </div>
          {auxiliaries.length > 0 && <ParticipantGroup title="试剂、催化剂与溶剂" eyebrow="AUXILIARIES" items={auxiliaries} showRole />}

          {(conditions.length > 0 || reaction.conditions_detail) && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>CONDITIONS</p><h2>反应条件</h2></div></div>
              {conditions.length > 0 && <dl className="condition-list">{conditions.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
              {reaction.conditions_detail && <p className="document-text">{reaction.conditions_detail}</p>}
            </section>
          )}
          {reaction.procedure_details && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>PROCEDURE</p><h2>实验过程</h2></div></div>
              <p className="document-text">{reaction.procedure_details}</p>
            </section>
          )}
          {(reaction.workup.length > 0 || reaction.workup_details) && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>WORKUP</p><h2>后处理</h2></div></div>
              {reaction.workup_details && <p className="document-text">{reaction.workup_details}</p>}
              {reaction.workup.length > 0 && <ol className="workup-list">{reaction.workup.map((step, index) => (
                <li key={index}><strong>{step.type ? unitName(step.type) : `步骤 ${index + 1}`}</strong><span>{[step.details, step.keep_phase ? `保留 ${step.keep_phase}` : null, step.target_ph != null ? `目标 pH ${step.target_ph}` : null].filter(Boolean).join(" · ") || "未记录说明"}</span></li>
              ))}</ol>}
            </section>
          )}
          {reaction.safety_notes && (
            <section className="reaction-section safety-panel">
              <div className="section-heading compact-heading"><div><p>SAFETY</p><h2>安全说明</h2></div></div>
              <p className="document-text">{reaction.safety_notes}</p>
            </section>
          )}
          {reaction.note && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>NOTE</p><h2>补充说明</h2></div></div>
              <p className="document-text">{reaction.note}</p>
            </section>
          )}
        </main>

        <aside className="reaction-aside">
          {reaction.creator && <section className="creator-card"><h2>创建者</h2><Link href={`/user/${reaction.creator.username}`}><span className="creator-avatar">{reaction.creator.avatar_url ? <img src={reaction.creator.avatar_url.replace(".webp", "-128.webp")} alt="" /> : reaction.creator.display_name.slice(0, 1)}</span><span><strong>{reaction.creator.display_name}</strong><small>@{reaction.creator.username}</small></span></Link><p>{reaction.visibility === "public" ? "公开反应" : "私有反应"} · 更新于 {new Date(reaction.updated_at).toLocaleDateString("zh-CN")}</p></section>}
          <section>
            <h2>来源与证据</h2>
            <dl>
              <Source label="来源类型" value={reaction.ord_id ? "Open Reaction Database" : sourceTypeName(reaction.source_type)} />
              <Source label="ORD 记录" value={reaction.ord_id} />
              <Source label="来源数据集" value={reaction.dataset_name} />
              <Source label="DOI" value={reaction.doi} href={reaction.doi ? `https://doi.org/${reaction.doi}` : undefined} />
              <Source label="专利" value={reaction.patent} />
              <Source label="原始链接" value={reaction.publication_url ? "查看来源" : null} href={reaction.publication_url || undefined} />
              <Source label="来源说明" value={reaction.source_citation} />
            </dl>
          </section>
          {reaction.reaction_smiles && <details className="source-expression">
            <summary>反应 SMILES</summary>
            <p className="mono">{reaction.reaction_smiles}</p>
          </details>}
        </aside>
      </div>
    </div>
  );
}

function ParticipantGroup({ title, eyebrow, items, showRole = false }: {
  title: string; eyebrow: string; items: Chemical[]; showRole?: boolean;
}) {
  return (
    <section className="participant-section">
      <div className="section-heading compact-heading"><div><p>{eyebrow}</p><h2>{title}</h2></div><span>{items.length}</span></div>
      {items.length > 0 ? <div className="participant-grid">{items.map((chemical) => (
        <Link className="participant-card" href={`/chemical/${chemical.id}`} key={`${chemical.role}-${chemical.id}`}>
          <div className="participant-structure"><Molecule smiles={chemical.smiles} width={220} height={140} /></div>
          <div>
            {showRole && <span className="role-label">{roleNames[chemical.role || ""] || chemical.role}</span>}
            <EntityId kind="chemical" id={chemical.id} compact />
            <h3>{chemical.preferred_name || chemical.iupac_name || "未命名化合物"}</h3>
            {chemical.molecular_formula && <p>{chemical.molecular_formula}</p>}
            {((chemical.occurrence_count != null && chemical.occurrence_count > 1) || chemical.amount_value != null || chemical.equivalents != null || chemical.concentration_value != null) && <p className="participant-measure-summary">{[
              chemical.occurrence_count != null && chemical.occurrence_count > 1 ? `${chemical.occurrence_count} 次` : null,
              chemical.amount_value != null ? `${chemical.amount_value} ${chemical.amount_unit || ""}` : null,
              chemical.equivalents != null ? `${chemical.equivalents} eq` : null,
              chemical.concentration_value != null ? `${chemical.concentration_value} ${chemical.concentration_unit || ""}` : null,
            ].filter(Boolean).join(" · ")}</p>}
            {chemical.yield_percent != null && <strong className="yield-value">收率 {formatYield(chemical.yield_percent)}%</strong>}
          </div>
        </Link>
      ))}</div> : <p className="quiet-empty">暂无{title}数据。</p>}
    </section>
  );
}

function Source({ label, value, href }: { label: string; value: string | null | undefined; href?: string }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd>{href ? <a href={href} target="_blank" rel="noreferrer">{value}</a> : value}</dd></div>;
}

function formatYield(value: number) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(value);
}

function unitName(value: string) {
  const labels: Record<string, string> = { CELSIUS: "°C", KELVIN: "K", MINUTE: "分钟", HOUR: "小时", DAY: "天" };
  return labels[value] || value.replaceAll("_", " ").toLowerCase();
}

function sourceTypeName(value: string | null) {
  const labels: Record<string, string> = { self: "本人实验", doi: "文献", patent: "专利", database: "数据库", url: "网页", other: "其他" };
  return value ? labels[value] || value : "未注明";
}
