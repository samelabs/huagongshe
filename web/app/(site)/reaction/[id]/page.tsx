import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { EntityId } from "@/components/shared/EntityId";
import { EntityNotes } from "@/components/EntityNotes";
import { FollowButton } from "@/components/shared/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionOwnerActions } from "@/components/ReactionOwnerActions";
import { apiGet, isApiNotFound, reactionSvgUrl, type Chemical, type ReactionDetail } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag, localizedAbsoluteUrl } from "@/lib/alternates";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import type { Locale } from "@/lib/i18n/locales";

/** 角色显示名按当前请求字典构建(原模块级常量依赖静态 zh 字典) */
function roleNames(t: Dictionary): Record<string, string> {
  return {
    REACTANT: t.submit.roles.reactant, REAGENT: t.submit.roles.reagent, CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
    PRODUCT: t.submit.roles.product, WORKUP: t.reaction.workup, INTERNAL_STANDARD: t.reaction.internalStandard, UNKNOWN: t.reaction.otherRole,
  };
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const canonical = `/reaction/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    title: `HRID ${id}`,
    description: t.reaction.desc,
    alternates: localeAlternates(canonical, locale),
    openGraph: { url: withLocale(canonical, locale), title: `HRID ${id}｜${t.brand.name}`, description: t.reaction.desc, locale: ogLocaleTag(locale) },
  };
}

export default async function ReactionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const locale: Locale = await getRequestLocale();
  const t = await getRequestDictionary();
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

  // 条件 = structured facts(独立字段); conditions_detail 只作补充说明, 不与 facts 混成一段。
  const conditions = [
    reaction.temperature ? [t.reaction.conditionFields.temperature, `${reaction.temperature.value} ${unitName(reaction.temperature.unit, t)}`] : null,
    reaction.duration ? [t.reaction.conditionFields.time, `${reaction.duration.value} ${unitName(reaction.duration.unit, t)}`] : null,
    reaction.atmosphere ? [t.reaction.conditionFields.atmosphere, reaction.atmosphere] : null,
    reaction.pressure ? [t.reaction.conditionFields.pressure, `${reaction.pressure.value} ${reaction.pressure.unit}`] : null,
    reaction.ph != null ? ["pH", String(reaction.ph)] : null,
    reaction.reflux ? [t.reaction.conditionFields.reflux, t.common.yes] : null,
  ].filter(Boolean) as string[][];

  // 结构化字段只来自当前 reaction (不推断命名反应/reaction class)
  const factualSummary = buildSummary(reactants, products, auxiliaries, reaction, t, locale);

  // Provenance: ORD 身份只认 ord_id; dataset_name / source_citation 在 API 中同源(见 services.reactions),
  // 只表达一次: 有 ORD 时是 ORD 数据集名, 否则是用户提供的来源说明。
  const hasOrd = Boolean(reaction.ord_id);
  const provenance: { label: string; value: string | null; href?: string }[] = [];
  if (hasOrd) provenance.push({ label: t.reaction.sourceFields.ord, value: reaction.ord_id });
  if (hasOrd && reaction.dataset_name) provenance.push({ label: t.reaction.sourceFields.dataset, value: reaction.dataset_name });
  if (!hasOrd && reaction.source_citation) provenance.push({ label: t.reaction.sourceFields.note, value: reaction.source_citation });
  if (reaction.source_type) provenance.push({ label: t.reaction.sourceFields.type, value: sourceTypeName(reaction.source_type, t) });
  if (reaction.doi) provenance.push({ label: t.reaction.sourceFields.doi, value: reaction.doi, href: `https://doi.org/${reaction.doi}` });
  if (reaction.patent) provenance.push({ label: t.reaction.sourceFields.patent, value: reaction.patent });
  if (reaction.publication_url) provenance.push({ label: t.reaction.sourceFields.link, value: t.reaction.sourceFields.viewSource, href: reaction.publication_url });

  const hasParticipants = reaction.participants.length > 0;
  const hasConditions = conditions.length > 0 || Boolean(reaction.conditions_detail);
  const hasProcedure = Boolean(reaction.procedure_details);
  const hasWorkup = reaction.workup.length > 0 || Boolean(reaction.workup_details);
  const hasSafety = Boolean(reaction.safety_notes);
  const hasNotes = Boolean(reaction.note);
  const hasSources = provenance.length > 0;

  // TOC 只列实际渲染的 section(rail 与 tablet/mobile local nav 共用此唯一列表)
  const tocSections: [string, string][] = [
    ...(hasParticipants ? [["participants", t.reaction.participants] as [string, string]] : []),
    ...(hasConditions ? [["conditions", t.reaction.conditions] as [string, string]] : []),
    ...(hasProcedure ? [["procedure", t.reaction.procedure] as [string, string]] : []),
    ...(hasWorkup ? [["workup", t.reaction.workup] as [string, string]] : []),
    ...(hasSafety ? [["safety", t.reaction.safety] as [string, string]] : []),
    ...(hasNotes ? [["notes", t.reaction.notes] as [string, string]] : []),
    ...(hasSources ? [["sources", t.reaction.sources] as [string, string]] : []),
    ["linked-notes", t.notes.linkedTitle],
  ];

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ChemicalReaction",
    name: t.reaction.jsonLdName(reaction.id),
    url: localizedAbsoluteUrl(`/reaction/${reaction.id}`, locale),
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
      <nav className="breadcrumbs" aria-label={t.common.breadcrumb}><Link href={withLocale(reaction.is_owner ? "/aichem" : "/", locale)}>{reaction.is_owner ? t.reaction.ownerSelf : t.reaction.ownerOther}</Link><span>/</span><span>{t.reaction.detail}</span></nav>

      {/* ── Reaction Entity Header ── */}
      <header className="reaction-title">
        <div>
          <EntityId kind="reaction" id={reaction.id} ariaLabel={t.common.hridLabel(reaction.id)} />
          <h1>{t.reaction.detail}</h1>
          {factualSummary && <p className="reaction-summary">{factualSummary}</p>}
        </div>
        {reaction.is_owner ? <ReactionOwnerActions reactionId={reaction.id} /> : <FollowButton endpoint={`/reactions/${reaction.id}/follow`} initial={reaction.is_following} count={reaction.follower_count} label="favor" />}
      </header>

      {/* ── Reaction Equation(实体签名对象, 紧接 header) ── */}
      <section className="reaction-equation" aria-labelledby="equation-title">
        <div className="section-heading"><div><p>EQUATION</p><h2 id="equation-title">{t.reaction.equation}</h2></div></div>
        {reaction.reaction_smiles ? <div className="reaction-scheme">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(reaction.id, 1500, 340)} width="1500" height="340" alt={t.reaction.equationAlt(reaction.id)} />
        </div> : <div className="reaction-scheme unavailable">{t.reaction.equationUnavailable}</div>}
      </section>

      {/* ── Tablet/Mobile local nav(rail 为桌面专属) ── */}
      <nav className="chem-local-nav" aria-label={t.chemical.page.onThisPage}>
        {tocSections.map(([anchor, label]) => <a key={anchor} href={`#${anchor}`}>{label}</a>)}
      </nav>

      <div className="reaction-layout">
        <main className="reaction-main">
          {hasParticipants && (
            <section className="chem-section" id="participants">
              <div className="section-heading"><div><h2>{t.reaction.participants}</h2></div><span>{reaction.participants.length}</span></div>
              <div className="reaction-sides">
                <ParticipantRoleGroup title={t.submit.roles.reactant} items={reactants} t={t} locale={locale} />
                <ParticipantRoleGroup title={t.submit.roles.product} items={products} t={t} locale={locale} />
              </div>
              {auxiliaries.length > 0 && <ParticipantRoleGroup title={t.reaction.reagentsCatalystsSolvents} items={auxiliaries} showRole t={t} locale={locale} />}
            </section>
          )}

          {hasConditions && (
            <section className="chem-section" id="conditions">
              <div className="section-heading"><div><h2>{t.reaction.conditions}</h2></div></div>
              {conditions.length > 0 && <dl className="condition-list">{conditions.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
              {reaction.conditions_detail && <p className="document-text">{reaction.conditions_detail}</p>}
            </section>
          )}

          {hasProcedure && (
            <section className="chem-section" id="procedure">
              <div className="section-heading"><div><h2>{t.reaction.procedure}</h2></div></div>
              <p className="document-text">{reaction.procedure_details}</p>
            </section>
          )}

          {hasWorkup && (
            <section className="chem-section" id="workup">
              <div className="section-heading"><div><h2>{t.reaction.workup}</h2></div></div>
              {reaction.workup_details && <p className="document-text">{reaction.workup_details}</p>}
              {reaction.workup.length > 0 && <ol className="workup-list">{reaction.workup.map((step, index) => (
                <li key={index}><strong>{step.type ? unitName(step.type, t) : t.reaction.stepLabel(index + 1)}</strong><span>{[step.details, step.keep_phase ? t.reaction.keepPhase(step.keep_phase) : null, step.target_ph != null ? t.reaction.targetPh(step.target_ph) : null].filter(Boolean).join(" · ") || t.reaction.errProcedure}</span></li>
              ))}</ol>}
            </section>
          )}

          {hasSafety && (
            <section className="chem-section safety-panel" id="safety">
              <div className="section-heading"><div><h2>{t.reaction.safety}</h2></div></div>
              <p className="document-text">{reaction.safety_notes}</p>
            </section>
          )}

          {hasNotes && (
            <section className="chem-section" id="notes">
              <div className="section-heading"><div><h2>{t.reaction.notes}</h2></div></div>
              <p className="document-text">{reaction.note}</p>
            </section>
          )}

          {hasSources && (
            <section className="chem-section" id="sources">
              <div className="section-heading"><div><h2>{t.reaction.sources}</h2></div></div>
              <div className="chem-sources">
                {provenance.map((row) => <ProvenanceRow key={row.label} label={row.label} value={row.value} href={row.href} />)}
              </div>
            </section>
          )}
          <EntityNotes entity="reaction" entityId={reaction.id} canAdd={hasSession} privateContext={hasSession ? { reaction: reaction.id } : undefined} />
        </main>

        {/* ── Secondary rail (desktop) ── */}
        <aside className="reaction-aside">
          <section>
            <h2>{t.chemical.page.onThisPage}</h2>
            <nav className="chem-toc">
              {tocSections.map(([anchor, label]) => <a key={anchor} href={`#${anchor}`}>{label}</a>)}
            </nav>
          </section>
          <section>
            <h2>{t.reaction.recordStatus}</h2>
            <dl>
              <div><dt>{t.reaction.fieldHrid}</dt><dd>HRID {reaction.id}</dd></div>
              <div><dt>{t.reaction.fieldVisibility}</dt><dd>{reaction.visibility === "public" ? t.reaction.publicReaction : t.reaction.privateReaction}{reaction.moderation_status !== "visible" && ` · ${t.reaction.hiddenRecord}`}</dd></div>
              <div><dt>{t.reaction.fieldCreated}</dt><dd>{formatDate(reaction.created_at, locale)}</dd></div>
              <div><dt>{t.reaction.fieldUpdated}</dt><dd>{formatDate(reaction.updated_at, locale)}</dd></div>
              {reaction.is_owner && <div><dt>{t.reaction.creator}</dt><dd>{t.reaction.ownerSelf}</dd></div>}
            </dl>
          </section>
          {reaction.creator && (
            <section className="creator-card">
              <h2>{t.reaction.creator}</h2>
              <Link href={withLocale(`/user/${reaction.creator.username}`, locale)}>
                <span className="creator-avatar">{reaction.creator.avatar_url ? <img src={reaction.creator.avatar_url.replace(".webp", "-128.webp")} alt="" /> : reaction.creator.display_name.slice(0, 1)}</span>
                <span><strong>{reaction.creator.display_name}</strong><small>@{reaction.creator.username}</small></span>
              </Link>
            </section>
          )}
          {reaction.reaction_smiles && (
            <details className="source-expression">
              <summary>{t.reaction.smiles}</summary>
              <p className="mono">{reaction.reaction_smiles}</p>
            </details>
          )}
        </aside>
      </div>
    </div>
  );
}

/* ── 小组件 ── */

/** 结构化字段拼出的一行事实摘要; 没有值的部分不显示, 不推断命名反应/反应类别。 */
function buildSummary(reactants: Chemical[], products: Chemical[], auxiliaries: Chemical[], reaction: ReactionDetail, t: Dictionary, locale: Locale): string {
  const parts: string[] = [];
  if (reactants.length > 0 || products.length > 0) {
    parts.push(`${t.reaction.summaryReactants(reactants.length)} → ${t.reaction.summaryProducts(products.length)}`);
  }
  const catalysts = auxiliaries.filter((item) => item.role === "CATALYST");
  const solvents = auxiliaries.filter((item) => item.role === "SOLVENT");
  if (catalysts.length > 0) parts.push(`${t.reaction.summaryCatalysts(catalysts.length)}${namedTail(catalysts, t, locale)}`);
  if (solvents.length > 0) parts.push(`${t.reaction.summarySolvents(solvents.length)}${namedTail(solvents, t, locale)}`);
  if (reaction.temperature) parts.push(`${reaction.temperature.value} ${unitName(reaction.temperature.unit, t)}`);
  if (reaction.duration) parts.push(`${reaction.duration.value} ${unitName(reaction.duration.unit, t)}`);
  return parts.join(" · ");
}

/** 最多带 2 个名字, 更多时只保留计数(不臆造 kind 名)。 */
function namedTail(items: Chemical[], t: Dictionary, locale: Locale): string {
  const names = items.slice(0, 2).map((item) => resolveChemicalName(item, t.common.hcidLabel, locale).title);
  if (names.length === 0) return "";
  return ` ${names.join("、")}${items.length > names.length ? ` ${t.reaction.summaryMore(items.length - names.length)}` : ""}`;
}

function ParticipantRoleGroup({ title, items, showRole = false, t, locale }: {
  title: string; items: Chemical[]; showRole?: boolean; t: Dictionary; locale: Locale;
}) {
  const roleLabels = roleNames(t);
  return (
    <section className="participant-section">
      <h3 className="chem-subhead">{title} <span className="chem-subhead-note">{items.length}</span></h3>
      {items.length > 0 ? <div className="participant-grid">{items.map((chemical) => (
        <Link className="participant-card" href={withLocale(`/chemical/${chemical.id}`, locale)} key={`${chemical.role}-${chemical.id}`}>
          <div className="participant-structure"><Molecule chemicalId={chemical.id} label={resolveChemicalName(chemical, t.common.hcidLabel, locale).title} width={220} height={140} alt={t.chemical.structureAlt(resolveChemicalName(chemical, t.common.hcidLabel, locale).title)} /></div>
          <div>
            {showRole && <span className="role-label">{roleLabels[chemical.role || ""] || chemical.role}</span>}
            <EntityId kind="chemical" id={chemical.id} compact ariaLabel={t.common.hcidLabel(chemical.id)} />
            <h3>{resolveChemicalName(chemical, t.common.hcidLabel, locale).title}</h3>
            {chemical.molecular_formula && <p>{chemical.molecular_formula}</p>}
            {((chemical.occurrence_count != null && chemical.occurrence_count > 1) || chemical.amount_value != null || chemical.equivalents != null || chemical.concentration_value != null) && <p className="participant-measure-summary">{[
              chemical.occurrence_count != null && chemical.occurrence_count > 1 ? t.reaction.occurrenceCount(chemical.occurrence_count) : null,
              chemical.amount_value != null ? `${chemical.amount_value} ${chemical.amount_unit || ""}` : null,
              chemical.equivalents != null ? `${chemical.equivalents} eq` : null,
              chemical.concentration_value != null ? `${chemical.concentration_value} ${chemical.concentration_unit || ""}` : null,
            ].filter(Boolean).join(" · ")}</p>}
            {chemical.yield_percent != null && <strong className="yield-value">{t.reaction.yieldLabel(formatYield(chemical.yield_percent, locale))}</strong>}
          </div>
        </Link>
      ))}</div> : <p className="quiet-empty">{t.chemical.knowledge.noData(title)}</p>}
    </section>
  );
}

function ProvenanceRow({ label, value, href }: { label: string; value: string | null | undefined; href?: string }) {
  if (!value) return null;
  // 0904 P1收口: publication_url 是用户输入(type=url 挡不住 javascript: 伪协议,
  // 结构上合法可过浏览器校验)。组件级守卫: 只渲染 http(s) 外链, 其余按纯文本出。
  const safeHref = href && /^https?:\/\//i.test(href) ? href : undefined;
  return (
    <div className="chem-source-row">
      <span className="chem-source-name">{label}</span>
      <span className="chem-source-meta">{safeHref ? <a href={safeHref} target="_blank" rel="nofollow noopener noreferrer">{value}</a> : value}</span>
    </div>
  );
}

function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(locale);
}

function formatYield(value: number, locale: string) {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value);
}

function unitName(value: string, t: Dictionary) {
  const labels: Record<string, string> = { CELSIUS: "°C", KELVIN: "K", MINUTE: t.reaction.timeUnits.minute, HOUR: t.reaction.timeUnits.hour, DAY: t.reaction.timeUnits.day };
  return labels[value] || value.replaceAll("_", " ").toLowerCase();
}

function sourceTypeName(value: string | null, t: Dictionary) {
  const labels: Record<string, string> = { self: t.reaction.sourceTypes.personal, doi: t.reaction.sourceTypes.literature, patent: t.reaction.sourceTypes.patent, database: t.reaction.sourceTypes.database, url: t.reaction.sourceTypes.webpage, other: t.reaction.sourceTypes.other };
  return value ? labels[value] || value : t.reaction.sourceTypes.unknown;
}
