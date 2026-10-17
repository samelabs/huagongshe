import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ChemPageNav } from "@/components/ChemPageNav";
import { DataRow } from "@/components/DataRow";
import { EntityNotes } from "@/components/EntityNotes";
import { ReactionOwnerActions } from "@/components/ReactionOwnerActions";
import { ShareButton } from "@/components/ShareButton";
import { Button } from "@/components/ui/Button";
import { IconPrinter } from "@/components/ui/icons";
import { FollowButton } from "@/components/shared/FollowButton";
import { Byline } from "@/components/ui/Byline";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { CodeField } from "@/components/ui/CodeField";
import { Notice } from "@/components/ui/Notice";
import { Tag } from "@/components/ui/Tag";
import { Molecule } from "@/components/Molecule";
import { apiGet } from "@/lib/api.server";
import { isApiGone, isEntityId, reactionSvgUrl, type Chemical, type ReactionDetail } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag, localizedAbsoluteUrl } from "@/lib/alternates";
import { buildShareMetadata } from "@/lib/shareMeta";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import type { Locale } from "@/lib/i18n/locales";

/**
 * Reaction Detail（DESIGN_SYSTEM 6.4 重排）。
 *
 * 头部：EntityBadge lg copyable（私有带锁）→ h1 中性「反应详情」（字号同化合物页）
 * → 结构化事实摘要（fs-16/text-2）→ 操作行（本人：编辑/可见性/删除；
 * 他人：关注 primary + 分享 ghost icon）。
 * 反应式：满宽白底卡片（手机可横向滚动不压缩）+ CodeField 反应 SMILES。
 * 参与物：按角色分组的紧凑行（64×48 缩略图 + 徽标 sm + 名称 + 用量）。
 * 数据行统一 DataRow；安全一节 Notice warn；右侧栏 = 本页导航（滚动高亮）
 * → 创建者 → 记录 → 引用；≤900 本页导航为吸顶横向 Tabs、侧栏移文末。
 * 只重组展示，数据请求不变（GET /reactions/{id} 带会话）。
 */

/** 角色显示名按当前请求字典构建(原模块级常量依赖静态 zh 字典) */
function roleNames(t: Dictionary): Record<string, string> {
  return {
    REACTANT: t.submit.roles.reactant, REAGENT: t.submit.roles.reagent, CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
    PRODUCT: t.submit.roles.product, WORKUP: t.reaction.workup, INTERNAL_STANDARD: t.reaction.internalStandard, UNKNOWN: t.reaction.otherRole,
  };
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  // 非法 ID 与页面同一口径 → 404
  if (!isEntityId(id)) notFound();
  const canonical = `/reaction/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const pageTitle = t.common.hridShort(id);
  const description = t.reaction.desc;
  // 匿名可访问（公开且存在）才有分享图；不公开或不存在用兜底横版品牌图
  const visible = await apiGet(`/reactions/${id}`).then(() => true).catch(() => false);
  const shareMeta = buildShareMetadata({
    title: `${pageTitle}｜${t.brand.name}`,
    description,
    path: canonical,
    locale,
    siteName: t.brand.name,
    ogImage: visible
      ? {
          url: `/img/reaction/${id}.png`,
          width: 1200,
          height: 630,
          alt: t.reaction.equationAlt(Number(id)),
        }
      : {
          url: "/og.png",
          width: 1200,
          height: 630,
          alt: `${pageTitle}｜${t.brand.name}`,
        },
    twitterCard: "summary_large_image",
  });
  return {
    title: pageTitle,
    description,
    alternates: localeAlternates(canonical, locale),
    ...shareMeta,
  };
}

export default async function ReactionPage({ params }: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // (/ HGS-WEB-DETAIL-ID-01）：非法 ID 直接 404；后端 422 同 404
  if (!isEntityId(id)) notFound();
  const locale: Locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const cookieStore = await cookies();
  const hasSession = cookieStore.has("hgs_session");
  const cookie = cookieStore.toString();
  let reaction: ReactionDetail;
  try {
    reaction = await apiGet<ReactionDetail>(`/reactions/${id}`, hasSession ? { Cookie: cookie } : undefined);
  } catch (error) { if (isApiGone(error)) notFound(); throw error; }

  const reactants = reaction.participants.filter((item) => item.role === "REACTANT");
  const products = reaction.participants.filter((item) => item.role === "PRODUCT");
  const auxiliaries = reaction.participants.filter((item) => item.role !== "REACTANT" && item.role !== "PRODUCT");

  // 主要反应物取第一个反应物；主要产物取有收率中最高的一个，都没有收率时取第一个产物（DESIGN_SYSTEM 5.1）
  const primaryReactantParticipant = reactants[0];
  const productsWithYield = products.filter((p) => typeof p.yield_percent === "number" && !isNaN(p.yield_percent));
  const primaryProductParticipant = productsWithYield.length > 0
    ? productsWithYield.reduce((max, cur) => ((cur.yield_percent ?? 0) > (max.yield_percent ?? 0) ? cur : max))
    : products[0];

  const primaryReactant = primaryReactantParticipant ? resolveChemicalName(primaryReactantParticipant, t.common.hcidLabel, locale).title : "";
  const primaryProduct = primaryProductParticipant ? resolveChemicalName(primaryProductParticipant, t.common.hcidLabel, locale).title : "";
  const reactionTitleText = (primaryReactant && primaryProduct)
    ? t.reaction.reactionTitle(primaryReactant, primaryProduct)
    : primaryReactant
      ? `${primaryReactant} →`
      : primaryProduct
        ? `→ ${primaryProduct}`
        : t.reaction.reactionTitleFallback(reaction.id);

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
      {/* 安全收口: JSON.stringify 不转义 '<', </script> 可闭合标签注入脚本
          (存储型XSS)。规范做法: < 与 U+2028/2029 转义为 JSON 等价形式。 */}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029") }} />
      <Breadcrumb
        items={[
          { label: t.chemical.home, href: withLocale("/", locale) },
          { label: t.reaction.category },
        ]}
        ariaLabel={t.common.breadcrumb}
      />

      {/* ── Reaction Entity Header（5.1 / 6.4：徽标 lg + 标题 + 事实摘要 + 操作行） ── */}
      <header className="rx-head">
        <div className="rx-badge-row">
          <EntityBadge
            kind="reaction"
            id={reaction.id}
            size="lg"
            state={reaction.visibility === "private" ? "private" : undefined}
            ariaLabel={t.common.hridLabel(reaction.id)}
          />
          <ShareButton title={t.reaction.jsonLdName(reaction.id)} iconOnly size="sm" ariaLabel={t.guide.share} />
          <Button variant="ghost" size="sm" iconOnly newWindow href={withLocale(`/reaction/${reaction.id}/print`, locale)} aria-label={t.common.print}>
            <IconPrinter />
          </Button>
        </div>
        <h1 className="rx-head-title">{reactionTitleText}</h1>
        {reaction.creator && (
          <div className="rx-head-byline">
            <Byline
              user={reaction.creator}
              time={t.reaction.publishedOn(new Date(reaction.created_at).toLocaleDateString(locale))}
              privateMark={reaction.visibility === "private"}
              size={32}
            />
            {/* 非作者关注作者的入口（停用账号不出，关注端点本就拒绝停用目标） */}
            {!reaction.is_owner && reaction.creator.active !== false && (
              <FollowButton
                endpoint={`/users/${encodeURIComponent(reaction.creator.username)}/follow`}
                initial={reaction.creator.is_following ?? false}
                showCount={false}
                size="sm"
                activeVariant="secondary"
                activeHoverText={t.follow.unfollow}
              />
            )}
          </div>
        )}
        {reaction.is_owner && reaction.moderation_status === "hidden" && (
          /* 作者可见的隐藏提示 —— 内容被治理隐藏时明确告知，不再是「无声」 */
          <Notice tone="warn">{t.reaction.hiddenNotice}</Notice>
        )}
        {factualSummary && <p className="rx-head-summary">{factualSummary}</p>}
        <div className="rx-head-actions">
          {reaction.is_owner ? (
            <ReactionOwnerActions reactionId={reaction.id} />
          ) : (
            <FollowButton endpoint={`/reactions/${reaction.id}/follow`} initial={reaction.is_following} count={reaction.follower_count} label="favor" />
          )}
        </div>
      </header>

      {/* ── Reaction Equation（满宽卡片 + CodeField SMILES；无 eyebrow） ── */}
      <section className="rx-equation" aria-labelledby="equation-title">
        <div className="section-heading chem-section-head"><h2 id="equation-title">{t.reaction.equation}</h2></div>
        <div className="rx-equation-card">
          {reaction.reaction_smiles ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={reactionSvgUrl(reaction.id)} width="1500" height="340" alt={t.reaction.equationAlt(reaction.id)} />
          ) : <div className="rx-equation-unavailable">{t.reaction.equationUnavailable}</div>}
        </div>
        {reaction.reaction_smiles && (
          <CodeField value={reaction.reaction_smiles} copyLabel={`${t.common.copy} SMILES`} className="rx-smiles-code" />
        )}
      </section>

      {/* ── ≤900 顶部横向 Tabs（桌面由右侧栏承担导航） ── */}
      <ChemPageNav sections={tocSections} variant="tabs" />

      <div className="chemical-layout">
        <main className="chemical-main">

          {hasParticipants && (
            <section className="chem-section" id="participants">
              <div className="section-heading chem-section-head"><h2>{t.reaction.participants}</h2><span>{reaction.participants.length}</span></div>
              <div className="reaction-sides">
                <ParticipantRoleGroup title={t.submit.roles.reactant} items={reactants} t={t} locale={locale} />
                <ParticipantRoleGroup title={t.submit.roles.product} items={products} t={t} locale={locale} />
              </div>
              {auxiliaries.length > 0 && <ParticipantRoleGroup title={t.reaction.reagentsCatalystsSolvents} items={auxiliaries} showRole t={t} locale={locale} />}
            </section>
          )}

          {hasConditions && (
            <section className="chem-section" id="conditions">
              <div className="section-heading chem-section-head"><h2>{t.reaction.conditions}</h2></div>
              <dl className="chem-dl">
                {conditions.map(([label, value]) => <DataRow key={label} label={label} value={value} />)}
                {reaction.conditions_detail && (
                  <DataRow label={t.reaction.conditionFields.other} value={reaction.conditions_detail} />
                )}
              </dl>
            </section>
          )}

          {hasProcedure && (
            <section className="chem-section" id="procedure">
              <div className="section-heading chem-section-head"><h2>{t.reaction.procedure}</h2></div>
              <p className="document-text">{reaction.procedure_details}</p>
            </section>
          )}

          {hasWorkup && (
            <section className="chem-section" id="workup">
              <div className="section-heading chem-section-head"><h2>{t.reaction.workup}</h2></div>
              {reaction.workup_details && <p className="document-text">{reaction.workup_details}</p>}
              {reaction.workup.length > 0 && <ol className="workup-list">{reaction.workup.map((step, index) => (
                <li key={index}><strong>{step.type ? unitName(step.type, t) : t.reaction.stepLabel(index + 1)}</strong><span>{[step.details, step.keep_phase ? t.reaction.keepPhase(step.keep_phase) : null, step.target_ph != null ? t.reaction.targetPh(step.target_ph) : null].filter(Boolean).join(" · ") || t.reaction.errProcedure}</span></li>
              ))}</ol>}
            </section>
          )}

          {hasSafety && (
            <section className="chem-section" id="safety">
              <div className="section-heading chem-section-head"><h2>{t.reaction.safety}</h2></div>
              <Notice tone="warn"><p className="document-text rx-safety-text">{reaction.safety_notes}</p></Notice>
            </section>
          )}

          {hasNotes && (
            <section className="chem-section" id="notes">
              <div className="section-heading chem-section-head"><h2>{t.reaction.notes}</h2></div>
              <p className="document-text">{reaction.note}</p>
            </section>
          )}

          {hasSources && (
            <section className="chem-section" id="sources">
              <div className="section-heading chem-section-head"><h2>{t.reaction.sources}</h2></div>
              <dl className="chem-dl">
                {provenance.map((row) => (
                  <DataRow key={row.label} label={row.label} value={row.value}>
                    {row.value && row.href && /^https?:\/\//i.test(row.href)
                      ? <a href={row.href} target="_blank" rel="nofollow noopener noreferrer">{row.value}</a>
                      : undefined}
                  </DataRow>
                ))}
              </dl>
            </section>
          )}
          <EntityNotes entity="reaction" entityId={reaction.id} canAdd={hasSession} privateContext={hasSession ? { reaction: reaction.id } : undefined} />
        </main>

        {/* ── Secondary rail (desktop；≤900 移到正文末尾) ── */}
        <aside className="chemical-aside">
          <ChemPageNav sections={tocSections} variant="rail" />
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
  const names = items.slice(0, 2).map((item) => dedupeParens(resolveChemicalName(item, t.common.hcidLabel, locale).title));
  if (names.length === 0) return "";
  return ` ${names.join("、")}${items.length > names.length ? ` ${t.reaction.summaryMore(items.length - names.length)}` : ""}`;
}

/** ：名称自带「外名 (内名)」且两者相同（忽略大小写与首尾空格）时
 * 只显示括号外部分（数据源 name_cn 与 preferred_name 同值时曾渲染「水杨酸 (水杨酸)」）。 */
function dedupeParens(name: string): string {
  const match = name.match(/^(.+?)\s*[（(](.+)[)）]\s*$/);
  if (!match) return name;
  const [, outer, inner] = match;
  return outer.trim().toLowerCase() === inner.trim().toLowerCase() ? outer.trim() : name;
}

/** 参与物（3.4 / 5.4 / 6.4 紧凑行）：64×48 缩略图 + 徽标 sm + 名称 + 用量/当量；桌面两列、手机一列 */
function ParticipantRoleGroup({ title, items, showRole = false, t, locale }: {
  title: string; items: Chemical[]; showRole?: boolean; t: Dictionary; locale: Locale;
}) {
  const roleLabels = roleNames(t);
  return (
    <section className="participant-section">
      <h3 className="chem-subhead">{title} <span className="chem-subhead-note">{items.length}</span></h3>
      {items.length > 0 ? <div className="participant-rows">{items.map((chemical) => {
        const name = resolveChemicalName(chemical, t.common.hcidLabel, locale).title;
        const measure = [
          chemical.occurrence_count != null && chemical.occurrence_count > 1 ? t.reaction.occurrenceCount(chemical.occurrence_count) : null,
          chemical.amount_value != null ? `${chemical.amount_value} ${chemical.amount_unit || ""}` : null,
          chemical.equivalents != null ? `${chemical.equivalents} eq` : null,
          chemical.concentration_value != null ? `${chemical.concentration_value} ${chemical.concentration_unit || ""}` : null,
        ].filter(Boolean).join(" · ");
        return (
          <Link className="participant-row" href={withLocale(`/chemical/${chemical.id}`, locale)} key={`${chemical.role}-${chemical.id}`}>
            <span className="participant-thumb"><Molecule chemicalId={chemical.id} smiles={chemical.smiles} label={name} size="xs" alt={t.chemical.structureAlt(name)} /></span>
            <span className="participant-id"><EntityBadge kind="chemical" id={chemical.id} size="sm" ariaLabel={t.common.hcidLabel(chemical.id)} /></span>
            <span className="participant-name">{name}</span>
            {showRole && <Tag>{roleLabels[chemical.role || ""] || chemical.role}</Tag>}
            {(measure || chemical.yield_percent != null) && (
              <span className="participant-measure">
                {measure}
                {chemical.yield_percent != null && <strong className="participant-yield">{t.reaction.yieldLabel(formatYield(chemical.yield_percent, locale))}</strong>}
              </span>
            )}
          </Link>
        );
      })}</div> : <p className="quiet-empty">{t.chemical.knowledge.noData(title)}</p>}
    </section>
  );
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
