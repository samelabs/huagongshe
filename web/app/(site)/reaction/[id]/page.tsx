import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { EntityId } from "@/components/shared/EntityId";
import { FollowButton } from "@/components/shared/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionOwnerActions } from "@/components/ReactionOwnerActions";
import { apiGet, isApiNotFound, reactionSvgUrl, type Chemical, type ReactionDetail } from "@/lib/api";
import t from "@/lib/i18n";

const roleNames: Record<string, string> = {
  REACTANT: t.submit.roles.reactant, REAGENT: t.submit.roles.reagent, CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
  PRODUCT: t.submit.roles.product, WORKUP: t.reaction.workup, INTERNAL_STANDARD: t.reaction.internalStandard, UNKNOWN: t.reaction.otherRole,
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `HRID ${id}`, description: t.reaction.desc };
}

export default async function ReactionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const cookieStore = await cookies();
  const hasSession = cookieStore.has("hgs_session");
  const cookie = cookieStore.toString();
  let reaction: ReactionDetail;
  try {
    reaction = await apiGet<ReactionDetail>(`/reactions/${id}`, hasSession ? { Cookie: cookie } : undefined);
  } catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  const reactants = reaction.participants.filter((item) => item.role === "REACTANT");
  const products = reaction.participants.filter((item) => item.role === "PRODUCT");
  const auxiliaries = reaction.participants.filter((item) => item.role !== "REACTANT" && item.role !== "PRODUCT");
  const conditions = [
    reaction.temperature ? [t.reaction.conditionFields.temperature, `${reaction.temperature.value} ${unitName(reaction.temperature.unit)}`] : null,
    reaction.duration ? [t.reaction.conditionFields.time, `${reaction.duration.value} ${unitName(reaction.duration.unit)}`] : null,
    reaction.atmosphere ? [t.reaction.conditionFields.atmosphere, reaction.atmosphere] : null,
    reaction.pressure ? [t.reaction.conditionFields.pressure, `${reaction.pressure.value} ${reaction.pressure.unit}`] : null,
    reaction.ph != null ? ["pH", String(reaction.ph)] : null,
    reaction.reflux ? [t.reaction.conditionFields.reflux, t.common.yes] : null,
  ].filter(Boolean) as string[][];

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ChemicalReaction",
    name: t.reaction.jsonLdName(reaction.id),
    url: `https://huagongshe.com/reaction/${reaction.id}`,
    ...(reaction.reaction_smiles ? { reactionSmiles: reaction.reaction_smiles } : {}),
    ...(reaction.doi ? { citation: { "@type": "CreativeWork", identifier: reaction.doi } } : {}),
    ...(reaction.procedure_details ? { description: reaction.procedure_details } : {}),
    ...(reaction.temperature ? { temperature: `${reaction.temperature.value} ${reaction.temperature.unit}` } : {}),
  };

  return (
    <div className="content-page reaction-page">
      {/* 0904 P0收口: JSON.stringify 不转义 '<', </script> 可闭合标签注入脚本
          (存储型XSS)。规范做法: < 与 U+2028/2029 转义为 JSON 等价形式。 */}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029") }} />
      <nav className="breadcrumbs" aria-label={t.common.breadcrumb}><Link href={reaction.is_owner ? "/aichem" : "/"}>{reaction.is_owner ? t.reaction.ownerSelf : t.reaction.ownerOther}</Link><span>/</span><span>{t.reaction.detail}</span></nav>
      <header className="reaction-title">
        <div>
          <EntityId kind="reaction" id={reaction.id} />
          <h1>{t.reaction.detail}</h1>
        </div>
        {reaction.is_owner ? <ReactionOwnerActions reactionId={reaction.id} /> : <FollowButton endpoint={`/reactions/${reaction.id}/follow`} initial={reaction.is_following} count={reaction.follower_count} label="favor" />}
      </header>

      <section className="reaction-equation" aria-labelledby="equation-title">
        <div className="section-heading compact-heading"><div><p>EQUATION</p><h2 id="equation-title">{t.reaction.equation}</h2></div></div>
        {reaction.reaction_smiles ? <div className="reaction-scheme">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(reaction.id, 1500, 340)} width="1500" height="340" alt={t.reaction.equationAlt(reaction.id)} />
        </div> : <div className="reaction-scheme unavailable">{t.reaction.equationUnavailable}</div>}
      </section>

      <div className="reaction-layout">
        <main className="reaction-main">
          <div className="reaction-sides">
            <ParticipantGroup title={t.submit.roles.reactant} eyebrow="REACTANTS" items={reactants} />
            <ParticipantGroup title={t.submit.roles.product} eyebrow="PRODUCTS" items={products} />
          </div>
          {auxiliaries.length > 0 && <ParticipantGroup title={t.reaction.reagentsCatalystsSolvents} eyebrow="AUXILIARIES" items={auxiliaries} showRole />}

          {(conditions.length > 0 || reaction.conditions_detail) && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>CONDITIONS</p><h2>{t.reaction.conditions}</h2></div></div>
              {conditions.length > 0 && <dl className="condition-list">{conditions.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
              {reaction.conditions_detail && <p className="document-text">{reaction.conditions_detail}</p>}
            </section>
          )}
          {reaction.procedure_details && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>PROCEDURE</p><h2>{t.reaction.procedure}</h2></div></div>
              <p className="document-text">{reaction.procedure_details}</p>
            </section>
          )}
          {(reaction.workup.length > 0 || reaction.workup_details) && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>WORKUP</p><h2>{t.reaction.workup}</h2></div></div>
              {reaction.workup_details && <p className="document-text">{reaction.workup_details}</p>}
              {reaction.workup.length > 0 && <ol className="workup-list">{reaction.workup.map((step, index) => (
                <li key={index}><strong>{step.type ? unitName(step.type) : t.reaction.stepLabel(index + 1)}</strong><span>{[step.details, step.keep_phase ? t.reaction.keepPhase(step.keep_phase) : null, step.target_ph != null ? t.reaction.targetPh(step.target_ph) : null].filter(Boolean).join(" · ") || t.reaction.errProcedure}</span></li>
              ))}</ol>}
            </section>
          )}
          {reaction.safety_notes && (
            <section className="reaction-section safety-panel">
              <div className="section-heading compact-heading"><div><p>SAFETY</p><h2>{t.reaction.safety}</h2></div></div>
              <p className="document-text">{reaction.safety_notes}</p>
            </section>
          )}
          {reaction.note && (
            <section className="reaction-section">
              <div className="section-heading compact-heading"><div><p>NOTE</p><h2>{t.reaction.notes}</h2></div></div>
              <p className="document-text">{reaction.note}</p>
            </section>
          )}
        </main>

        <aside className="reaction-aside">
          {reaction.creator && <section className="creator-card"><h2>{t.reaction.creator}</h2><Link href={`/user/${reaction.creator.username}`}><span className="creator-avatar">{reaction.creator.avatar_url ? <img src={reaction.creator.avatar_url.replace(".webp", "-128.webp")} alt="" /> : reaction.creator.display_name.slice(0, 1)}</span><span><strong>{reaction.creator.display_name}</strong><small>@{reaction.creator.username}</small></span></Link><p>{reaction.visibility === "public" ? t.reaction.publicReaction : t.reaction.privateReaction} · {t.reaction.updated(new Date(reaction.updated_at).toLocaleDateString("zh-CN"))}</p></section>}
          <section>
            <h2>{t.reaction.sources}</h2>
            <dl>
              <Source label={t.reaction.sourceFields.type} value={reaction.ord_id ? "Open Reaction Database" : sourceTypeName(reaction.source_type)} />
              <Source label={t.reaction.sourceFields.ord} value={reaction.ord_id} />
              <Source label={t.reaction.sourceFields.dataset} value={reaction.dataset_name} />
              <Source label={t.reaction.sourceFields.doi} value={reaction.doi} href={reaction.doi ? `https://doi.org/${reaction.doi}` : undefined} />
              <Source label={t.reaction.sourceFields.patent} value={reaction.patent} />
              <Source label={t.reaction.sourceFields.link} value={reaction.publication_url ? t.reaction.sourceFields.viewSource : null} href={reaction.publication_url || undefined} />
              <Source label={t.reaction.sourceFields.note} value={reaction.source_citation} />
            </dl>
          </section>
          {reaction.reaction_smiles && <details className="source-expression">
            <summary>{t.reaction.smiles}</summary>
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
          <div className="participant-structure"><Molecule chemicalId={chemical.id} label={chemical.preferred_name || chemical.iupac_name} width={220} height={140} /></div>
          <div>
            {showRole && <span className="role-label">{roleNames[chemical.role || ""] || chemical.role}</span>}
            <EntityId kind="chemical" id={chemical.id} compact />
            <h3>{chemical.preferred_name || chemical.iupac_name || t.common.unnamedCompound}</h3>
            {chemical.molecular_formula && <p>{chemical.molecular_formula}</p>}
            {((chemical.occurrence_count != null && chemical.occurrence_count > 1) || chemical.amount_value != null || chemical.equivalents != null || chemical.concentration_value != null) && <p className="participant-measure-summary">{[
              chemical.occurrence_count != null && chemical.occurrence_count > 1 ? `${chemical.occurrence_count} 次` : null,
              chemical.amount_value != null ? `${chemical.amount_value} ${chemical.amount_unit || ""}` : null,
              chemical.equivalents != null ? `${chemical.equivalents} eq` : null,
              chemical.concentration_value != null ? `${chemical.concentration_value} ${chemical.concentration_unit || ""}` : null,
            ].filter(Boolean).join(" · ")}</p>}
            {chemical.yield_percent != null && <strong className="yield-value">{t.reaction.yieldLabel(formatYield(chemical.yield_percent))}</strong>}
          </div>
        </Link>
      ))}</div> : <p className="quiet-empty">{t.chemical.knowledge.noData(title)}</p>}
    </section>
  );
}

function Source({ label, value, href }: { label: string; value: string | null | undefined; href?: string }) {
  if (!value) return null;
  // 0904 P1收口: publication_url 是用户输入(type=url 挡不住 javascript: 伪协议,
  // 结构上合法可过浏览器校验)。组件级守卫: 只渲染 http(s) 外链, 其余按纯文本出。
  const safeHref = href && /^https?:\/\//i.test(href) ? href : undefined;
  return <div><dt>{label}</dt><dd>{safeHref ? <a href={safeHref} target="_blank" rel="nofollow noopener noreferrer">{value}</a> : value}</dd></div>;
}

function formatYield(value: number) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(value);
}

function unitName(value: string) {
  const labels: Record<string, string> = { CELSIUS: "°C", KELVIN: "K", MINUTE: t.reaction.timeUnits.minute, HOUR: t.reaction.timeUnits.hour, DAY: "天" };
  return labels[value] || value.replaceAll("_", " ").toLowerCase();
}

function sourceTypeName(value: string | null) {
  const labels: Record<string, string> = { self: t.reaction.sourceTypes.personal, doi: t.reaction.sourceTypes.literature, patent: t.reaction.sourceTypes.patent, database: t.reaction.sourceTypes.database, url: t.reaction.sourceTypes.webpage, other: t.reaction.sourceTypes.other };
  return value ? labels[value] || value : t.reaction.sourceTypes.unknown;
}
