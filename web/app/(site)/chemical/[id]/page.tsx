import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { DetailRefresher } from "@/components/DetailRefresher";
import { EntityId } from "@/components/shared/EntityId";
import { FollowButton } from "@/components/shared/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionList } from "@/components/ReactionList";
import { ShareButton } from "@/components/ShareButton";
import { SynonymExplorer } from "@/components/SynonymExplorer";
import { cbNameGroups, industryGroups, propertyGroups, safetyGroups, type CasExternalsPayload } from "@/components/chemicalSections";
import { cbInFlight } from "@/components/chemicalStatus";
import { evidenceSectionKeys, isSummary, type EvidenceEntry } from "@/components/chemicalEvidence";
import { apiGet, isApiNotFound, type Chemical, type ChemicalDetails, type EnrichmentState, type ReactionSummary } from "@/lib/api";
import t from "@/lib/i18n";
import { resolveChemicalName } from "@/lib/chemicalName";

/**
 * Chemical Detail — semantic-first (Design System v2, Issue #4)。
 *
 * 一级 IA = 语义主题, 来源只是 evidence:
 *   Overview → Names & Identifiers → Properties → Safety & Regulatory
 *   → Chemistry & Industry → Reactions → Sources
 * 硬约束: 不为视觉整合发明数据合并; CB/PB 各自保留原值与来源。
 */

type DetailResponse = { details: ChemicalDetails | null; enrichment: EnrichmentState };

const SYN_PREVIEW = 10; // Names 默认展示条数(8–12 区间取 10)

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const canonical = `/chemical/${id}`;
  const chemical = await apiGet<Chemical>(`/chemicals/${id}?display=true`).catch(() => null);
  // 与页面 H1 同源: 同一 resolver、同一 locale, 不允许 SEO 自己再写一套 fallback
  const { title: displayName } = resolveChemicalName({ ...(chemical ?? {}), id }, t.common.hcidLabel);
  const pageTitle = `${displayName} (HCID ${id})`;
  const description = t.chemical.descFor(displayName);
  return {
    title: pageTitle,
    description,
    alternates: { canonical },
    openGraph: {
      url: canonical,
      title: `${pageTitle}｜${t.brand.name}`,
      description,
      images: [{ url: `/api/mol/${id}/png`, width: 500, height: 375, alt: `${displayName} 分子结构式` }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${pageTitle}｜${t.brand.name}`,
      description,
      images: [`/api/mol/${id}/png`],
    },
  };
}

export default async function ChemicalPage({ params }: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const hasSession = (await cookies()).has("hgs_session");
  // 0902 P0: SSR 透传用户凭证(详情页 QPS 低可接受, 沿用)
  const sessionHeaders = hasSession
    ? { cookie: `hgs_session=${(await cookies()).get("hgs_session")?.value ?? ""}` }
    : undefined;

  const [chemicalResult, reactionsResult, externalsResult] = await Promise.all([
    apiGet<Chemical>(`/chemicals/${id}?enrich=full&display=true`, sessionHeaders).catch((error: unknown) => {
      if (isApiNotFound(error)) notFound();
      throw error;
    }),
    apiGet<{ total: number; page: number; page_size: number; reactions: ReactionSummary[] }>(
      `/chemicals/${id}/reactions?page=1&page_size=8&role=any`,
    ).catch(() => null),
    apiGet<CasExternalsPayload>(`/chemicals/${id}/externals`, sessionHeaders).catch(() => null),
  ]);
  const chemical = chemicalResult;
  const externals = externalsResult;
  const reactionsUnavailable = reactionsResult === null;
  const initialReactions = reactionsResult?.reactions ?? [];
  const reactionTotal = reactionsResult?.total ?? 0;

  const details: DetailResponse = { details: chemical.details || null, enrichment: chemical.enrichment || { status: "current" } };
  const pb = details.details;
  const pbSections = pb ? evidenceSectionKeys(pb as unknown as Record<string, unknown>) : {};

  // 内部补全在途判定(不再向 UI 暴露数据源状态): CB queued → 继续轮询;
  // 空数据不算在途, 否则 fresh negative 会被持续轮询。
  const cbPending = cbInFlight(externals?.state);
  const refreshActive = details.enrichment.status === "queued" || cbPending;

  // 名称解析唯一出口(与搜索结果/SEO 同规则); pb.record_title 不再入链 ——
  // 数据事实: PubChem 摄入时 preferred_name = properties.Title or record_title,
  // 抽样 6/6 record_title 与 preferred_name 同值, 单独入链只会制造第二套 fallback。
  const { title, secondary } = resolveChemicalName(chemical, t.common.hcidLabel);
  const identifiers = identifierGroups(chemical);
  const names = cbNameGroups(externals, [chemical.preferred_name, chemical.iupac_name].filter((v): v is string => Boolean(v)));
  const props = propertyGroups(externals);
  const safety = safetyGroups(externals);
  const industry = industryGroups(externals);

  // Names: synonyms(主源) + CB aliases 视觉去重(仅展示层, 不写回)
  const synonyms = chemical.synonyms || [];
  const synTotal = chemical.synonym_count || 0;
  // 名称别名 union(仅展示层): identical string 只显示一次; CB aliases 并入同一条流,
  // 不再因 synonyms 占满 preview 而被丢弃 —— 展开区可见全部。
  const synLower = new Set(synonyms.map((s) => s.trim().toLowerCase()));
  const cbAliasOnly = names.aliases.filter((a) => !synLower.has(a.trim().toLowerCase()));
  const aliasUnion: { value: string; source: "syn" | "cb" }[] = [
    ...synonyms.map((v) => ({ value: v, source: "syn" as const })),
    ...cbAliasOnly.map((v) => ({ value: v, source: "cb" as const })),
  ];
  const previewAliases = aliasUnion.slice(0, SYN_PREVIEW);
  const synShownInPreview = previewAliases.filter((a) => a.source === "syn").length;
  const cbRest = aliasUnion.slice(SYN_PREVIEW).filter((a) => a.source === "cb");
  const hasAliasRest = aliasUnion.length > SYN_PREVIEW;

  // computed descriptors 是 Properties 的一部分: 只有 computed 的记录也必须渲染该 section
  const hasComputed = Boolean(pb) && [pb?.xlogp, pb?.topological_polar_surface_area, pb?.hbond_donor_count, pb?.hbond_acceptor_count,
    pb?.rotatable_bond_count, pb?.heavy_atom_count, pb?.formal_charge, pb?.complexity].some((v) => v != null);
  const hasProperties = hasComputed || props.cbExperimental.length > 0 || props.cbChemicalProse.length > 0
    || (pbSections["physical_properties"]?.length ?? 0) > 0;
  const hasSafetyReal = ["ghs_classification", "hazards", "safety_measures", "toxicity", "regulatory"].some(
    (k) => (pbSections[k]?.length ?? 0) > 0) || safety.cbSafety.length > 0 || safety.cbToxicity.length > 0 || safety.cbPackaging.length > 0;
  const hasIndustry = industry.uses.length > 0 || industry.preparation.length > 0 || industry.updown.length > 0
    || industry.price.length > 0 || industry.suppliers.length > 0
    || (pbSections["pharmacology"]?.length ?? 0) > 0 || (pbSections["uses_and_manufacturing"]?.length ?? 0) > 0;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "MolecularEntity",
    name: title,
    ...(secondary ? { alternateName: secondary } : {}),
    ...(chemical.iupac_name ? { iupacName: chemical.iupac_name } : {}),
    ...(chemical.molecular_formula ? { molecularFormula: chemical.molecular_formula } : {}),
    ...(chemical.molecular_formula ? { molecularWeight: chemical.average_mass ? String(chemical.average_mass) : undefined } : {}),
    ...(chemical.smiles ? { smiles: chemical.smiles } : {}),
    ...(chemical.inchikey ? { inChIKey: chemical.inchikey } : {}),
    ...(chemical.cas_numbers.length ? { casNumber: chemical.cas_numbers[0] } : {}),
    ...(chemical.pubchem_cid ? { url: `https://huagongshe.com/chemical/${chemical.id}` } : {}),
  };

  // TOC 只列实际渲染的 section(rail TOC 与 tablet/mobile local nav 共用此唯一列表)
  const tocSections: [string, string][] = [
    ["overview", t.chemical.page.overview],
    ["names", t.chemical.page.names],
    ...(hasProperties ? [["properties", t.chemical.page.properties] as [string, string]] : []),
    ...(hasSafetyReal ? [["safety", t.chemical.page.safety] as [string, string]] : []),
    ...(hasIndustry ? [["industry", t.chemical.page.industry] as [string, string]] : []),
    ["reactions", t.chemical.relatedReactions],
  ];

  return (
    <div className="content-page chemical-page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029") }} />
      <nav className="breadcrumbs" aria-label={t.common.breadcrumb}><Link href="/">{t.chemical.home}</Link><span>/</span><span>{t.chemical.detail}</span></nav>

      {/* ── Chemical Entity Header ── */}
      <header className="chemical-identity">
        <div className="chemical-structure"><Molecule chemicalId={chemical.id} label={title} width={360} height={280} /></div>
        <div className="chemical-title-block">
          <EntityId kind="chemical" id={chemical.id} />
          <h1>{title}</h1>
          {secondary && <p className="iupac-name">{secondary}</p>}
          {chemical.iupac_name && chemical.iupac_name.toLowerCase() !== title.toLowerCase()
            && chemical.iupac_name.toLowerCase() !== (secondary || "").toLowerCase()
            && <p className="iupac-name">{chemical.iupac_name}</p>}
          <div className="identity-primary">
            {chemical.molecular_formula && <span>{chemical.molecular_formula}</span>}
            {chemical.average_mass != null && <span>{formatNumber(chemical.average_mass)} g/mol</span>}
            {chemical.cas_numbers[0] && <span>CAS {chemical.cas_numbers[0]}</span>}
          </div>
          <div className="context-actions">
            <FollowButton endpoint={`/chemicals/${chemical.id}/follow`} initial={Boolean(chemical.is_following)} count={chemical.follower_count || 0} label="favor" />
            <ShareButton title={title} />
          </div>
          <div className="context-secondary-actions">
            {hasSession ? (<>
              <Link className="text-button" href={`/search?chemical_id=${chemical.id}&mode=substructure`}>{t.chemical.substructure}</Link>
              <Link className="text-button" href={`/search?chemical_id=${chemical.id}&mode=similarity`}>{t.chemical.similarity}</Link>
            </>) : (
              <Link className="text-button" href={`/login?next=${encodeURIComponent(`/chemical/${chemical.id}`)}`}>{t.chemical.structureLogin}</Link>
            )}
          </div>
        </div>
      </header>

      {/* ── Tablet/Mobile local nav(rail 桌面专属) ── */}
      <nav className="chem-local-nav" aria-label={t.chemical.page.onThisPage}>
        {tocSections.map(([anchor, label]) => <a key={anchor} href={`#${anchor}`}>{label}</a>)}
      </nav>

      <div className="chemical-layout">
        <main className="chemical-main">

          {/* ── 1. Overview ── */}
          <section className="chem-section" id="overview">
            <SectionHead anchor="overview" eyebrow="OVERVIEW" title={t.chemical.page.overview} />
            {pb?.record_description && <div className="description-panel"><p>{pb.record_description}</p></div>}
            <DetailRefresher active={refreshActive} />
            <dl className="identity-table">
              <Identity label={t.chemical.identity.standardSmiles} value={chemical.smiles} mono />
              <Identity label="InChIKey" value={chemical.inchikey} mono />
              <Identity label={t.chemical.identity.formula} value={chemical.molecular_formula} />
              <Identity label={t.chemical.identity.avgMass} value={chemical.average_mass != null ? `${formatNumber(chemical.average_mass)} g/mol` : null} />
              <Identity label={t.chemical.identity.monoMass} value={chemical.monoisotopic_mass != null ? formatNumber(chemical.monoisotopic_mass, 8) : null} />
            </dl>
          </section>

          {/* ── 2. Names & Identifiers ── */}
          <section className="chem-section" id="names">
            <SectionHead anchor="names" eyebrow="NAMES" title={t.chemical.page.names} />
            <dl className="identity-table">
              <Identity label={t.chemical.names.preferred} value={chemical.preferred_name} />
              <Identity label="IUPAC" value={chemical.iupac_name} />
              {names.identity.map((row) => <Identity key={row.label} label={row.label} value={row.value} />)}
            </dl>
            {(synTotal > 0 || cbAliasOnly.length > 0) && (
              <div className="chem-names-block">
                {/* 不显示 aggregate 总数: 视觉列表是 synonyms + CB aliases 去重 union, 无可靠 union total */}
                <h3 className="chem-subhead">{t.chemical.synonyms.title}</h3>
                <div className="alias-list">
                  {previewAliases.map((a) => <span key={`${a.source}-${a.value}`} className={a.source === "cb" ? "casext-tag" : undefined}>{a.value}</span>)}
                </div>
                {hasAliasRest && (
                  <details className="synonym-disclosure">
                    <summary>{t.chemical.synonyms.expandMore}</summary>
                    <div className="alias-list synonym-full">
                      {cbRest.map((a) => <span key={`cb-${a.value}`} className="casext-tag">{a.value}</span>)}
                      <SynonymExplorer chemicalId={chemical.id} initial={synonyms} total={synTotal} shown={synShownInPreview} />
                    </div>
                  </details>
                )}
              </div>
            )}
            {identifiers.length > 0 && (
              <div className="chem-names-block">
                <h3 className="chem-subhead">{t.chemical.page.dbIdentifiers}</h3>
                <dl className="identity-table">
                  {identifiers.map(([label, values]) => <div key={label}><dt>{label}</dt><dd>{values.join("、")}</dd></div>)}
                </dl>
              </div>
            )}
          </section>

          {/* ── 3. Properties ── */}
          {hasProperties && (
            <section className="chem-section" id="properties">
              <SectionHead anchor="properties" eyebrow="PROPERTIES" title={t.chemical.page.properties} />
              {pb && <ComputedDescriptors details={pb} enrichment={details.enrichment} />}
              {(pbSections["physical_properties"]?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.knowledge.experimental}</h3>
                  <EvidenceList entries={pbSections["physical_properties"]} />
                </div>
              )}
              {props.cbExperimental.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.props}</h3>
                  <dl className="identity-table">
                    {props.cbExperimental.map((p) => <div key={p.label}><dt>{p.label}</dt><dd>{p.value}</dd></div>)}
                  </dl>
                </div>
              )}
              {props.cbChemicalProse.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.chemicalProps}</h3>
                  <ProseList prose={props.cbChemicalProse} />
                </div>
              )}
            </section>
          )}

          {/* ── 4. Safety & Regulatory ── */}
          {hasSafetyReal && (
            <section className="chem-section" id="safety">
              <SectionHead anchor="safety" eyebrow="SAFETY" title={t.chemical.page.safety} />
              {(["ghs_classification", "hazards", "safety_measures", "toxicity", "regulatory"] as const).map((key) =>
                (pbSections[key]?.length ?? 0) > 0 ? (
                  <div className="chem-sub-block" key={key}>
                    <h3 className="chem-subhead">{pbSectionTitle(key)}</h3>
                    <EvidenceList entries={pbSections[key]} />
                  </div>
                ) : null)}
              {safety.cbSafety.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.safety}</h3>
                  <dl className="identity-table">
                    {safety.cbSafety.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
                  </dl>
                </div>
              )}
              {safety.cbToxicity.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.toxicity}</h3>
                  <ProseList prose={safety.cbToxicity} />
                </div>
              )}
              {safety.cbPackaging.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.packaging}</h3>
                  <ProseList prose={safety.cbPackaging} />
                </div>
              )}
            </section>
          )}

          {/* ── 5. Chemistry & Industry ── */}
          {hasIndustry && (
            <section className="chem-section" id="industry">
              <SectionHead anchor="industry" eyebrow="INDUSTRY" title={t.chemical.page.industry} />
              {(pbSections["pharmacology"]?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.knowledge.pharmacology}</h3>
                  <EvidenceList entries={pbSections["pharmacology"]} />
                </div>
              )}
              {(pbSections["uses_and_manufacturing"]?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.knowledge.uses}</h3>
                  <EvidenceList entries={pbSections["uses_and_manufacturing"]} />
                </div>
              )}
              {industry.uses.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.uses}</h3>
                  <ProseList prose={industry.uses} />
                </div>
              )}
              {industry.preparation.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.preparation}</h3>
                  <ProseList prose={industry.preparation} />
                </div>
              )}
              {industry.updown.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.updown}</h3>
                  <div className="casext-updown">
                    {(["up", "down"] as const).map((dir) => {
                      const items = industry.updown.filter((n) => n.direction === dir);
                      if (!items.length) return null;
                      return <div key={dir}><h4>{dir === "up" ? t.chemical.casext.upstream : t.chemical.casext.downstream}</h4><div className="casext-tags">{items.map((n) => <span key={`${dir}-${n.name}`} className="casext-tag">{n.name}</span>)}</div></div>;
                    })}
                  </div>
                </div>
              )}
              {industry.price.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.price}</h3>
                  <dl className="identity-table">
                    {industry.price.map((r) => <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>)}
                  </dl>
                </div>
              )}
              {industry.suppliers.length > 0 && (
                <div className="chem-sub-block" id="suppliers">
                  <h3 className="chem-subhead">{t.chemical.casext.suppliers} <span className="chem-subhead-note">{new Intl.NumberFormat("zh-CN").format(industry.suppliers.length)} {t.chemical.casext.supplierUnit}</span></h3>
                  <div className="casext-suppliers">
                    {industry.suppliers.map((s) => <SupplierCard key={s.ref} supplier={s} />)}
                  </div>
                </div>
              )}
              {industry.notes.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.safetyNotes}</h3>
                  <ProseList prose={industry.notes} />
                </div>
              )}
            </section>
          )}

          {/* ── 6. Reactions ── */}
          <section className="chem-section" id="reactions">
            <SectionHead anchor="reactions" eyebrow="REACTIONS" title={t.chemical.relatedReactions}
              note={!reactionsUnavailable ? `${new Intl.NumberFormat("zh-CN").format(reactionTotal)} 条` : undefined} />
            {reactionsUnavailable ? <p className="quiet-empty">{t.chemical.errReactions}</p> : <ReactionList chemicalId={chemical.id} initial={initialReactions} initialTotal={reactionTotal} />}
          </section>

        </main>

        {/* ── Secondary rail (desktop) ── */}
        <aside className="chemical-aside">
          <section>
            <h2>{t.chemical.page.onThisPage}</h2>
            <nav className="chem-toc">
              {tocSections.map(([anchor, label]) => <a key={anchor} href={`#${anchor}`}>{label}</a>)}
            </nav>
          </section>
          <section>
            <h2>{t.chemical.page.keyIdentifiers}</h2>
            <dl>
              {chemical.cas_numbers[0] && <div><dt>CAS</dt><dd>{chemical.cas_numbers.join("、")}</dd></div>}
              {chemical.pubchem_cid != null && <div><dt>PubChem CID</dt><dd>{chemical.pubchem_cid}</dd></div>}
              {chemical.inchikey && <div><dt>InChIKey</dt><dd className="mono chem-rail-id">{chemical.inchikey}</dd></div>}
            </dl>
          </section>
          <section className="contribute-panel">
            <h2>{t.chemical.newRelated}</h2>
            <p>{t.chemical.newRelatedHint}</p>
            <Link href={`/submit?chemical=${chemical.id}`} rel="nofollow">{t.chemical.newReaction}</Link>
          </section>
        </aside>
      </div>
    </div>
  );
}

/* ── 小组件 ── */

function SectionHead({ anchor, eyebrow, title, note }: { anchor: string; eyebrow: string; title: string; note?: string }) {
  return (
    <div className="section-heading" id={`${anchor}-head`}>
      <div><p>{eyebrow}</p><h2>{title}</h2></div>
      {note && <span>{note}</span>}
    </div>
  );
}

function Identity({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd className={mono ? "mono" : ""}>{value}</dd></div>;
}

function ComputedDescriptors({ details, enrichment }: { details: ChemicalDetails; enrichment: EnrichmentState }) {
  const hasAny = details.xlogp != null || details.topological_polar_surface_area != null || details.hbond_donor_count != null
    || details.hbond_acceptor_count != null || details.rotatable_bond_count != null || details.heavy_atom_count != null
    || details.formal_charge != null || details.complexity != null;
  if (!hasAny) return null;
  return (
    <div className="chem-sub-block">
      <h3 className="chem-subhead">{t.chemical.knowledge.descriptors}{enrichment.status !== "current" && <span className="chem-subhead-note">{enrichment.status === "stale" ? t.chemical.page.statusStale : t.chemical.page.statusQueued}</span>}</h3>
      <dl className="metric-grid">
        <Metric label="XLogP" value={details.xlogp} />
        <Metric label={t.chemical.knowledge.tpsa} value={details.topological_polar_surface_area} suffix=" Å²" />
        <Metric label={t.chemical.knowledge.hbd} value={details.hbond_donor_count} />
        <Metric label={t.chemical.knowledge.hba} value={details.hbond_acceptor_count} />
        <Metric label={t.chemical.knowledge.rotatable} value={details.rotatable_bond_count} />
        <Metric label={t.chemical.knowledge.heavyAtoms} value={details.heavy_atom_count} />
        <Metric label={t.chemical.knowledge.charge} value={details.formal_charge} />
        <Metric label={t.chemical.knowledge.complexity} value={details.complexity} />
      </dl>
    </div>
  );
}

function Metric({ label, value, suffix = "" }: { label: string; value: number | null | undefined; suffix?: string }) {
  if (value == null) return null;
  return <div><dt>{label}</dt><dd>{new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(value)}{suffix}</dd></div>;
}

/** disclosure 新规: 摘要(短)直接可见, 长列表默认折叠 — 不删数据。 */
function EvidenceList({ entries }: { entries: EvidenceEntry[] }) {
  return (
    <div className="evidence-list">
      {entries.map((entry, index) => (
        entry.values.length === 1 && isSummary(entry) ? (
          <div key={`${entry.label}-${index}`} className="evidence-flat">
            <dt>{entry.label}</dt>
            <dd>{entry.values[0]}</dd>
          </div>
        ) : (
          <details key={`${entry.label}-${index}`}>
            <summary>{entry.label}<span className="evidence-count">{entry.values.length}</span></summary>
            <div>{entry.values.map((value, vi) => <p key={vi}>{value}</p>)}</div>
          </details>
        )
      ))}
    </div>
  );
}

function ProseList({ prose }: { prose: { title: string; text: string }[] }) {
  return (
    <div className="casext-prose-list">
      {prose.map((item) => <p key={item.title + item.text.slice(0, 24)}><strong>{item.title}</strong>{item.text}</p>)}
    </div>
  );
}

function SupplierCard({ supplier }: { supplier: { ref: string; name: string; phone: string | null; email: string | null; website: string | null; purity: string | null; pack_price: string | null; remark: string | null } }) {
  const { name, phone, email, website, purity, pack_price, remark } = supplier;
  return (
    <article className="casext-supplier">
      <header><h3>{name}</h3></header>
      <dl>
        {purity && <div><dt>{t.chemical.casext.purity}</dt><dd>{purity}</dd></div>}
        {pack_price && <div><dt>{t.chemical.casext.packPrice}</dt><dd>{pack_price}</dd></div>}
        {phone && <div><dt>{t.chemical.casext.phone}</dt><dd>{phone}</dd></div>}
        {email && <div><dt>{t.chemical.casext.email}</dt><dd>{email}</dd></div>}
        {website && (
          <div><dt>{t.chemical.casext.website}</dt><dd>
            <a href={website.startsWith("http") ? website : `https://${website}`} target="_blank" rel="nofollow noopener noreferrer">{website}</a>
          </dd></div>
        )}
        {remark && <div><dt>{t.chemical.casext.remark}</dt><dd>{remark}</dd></div>}
      </dl>
    </article>
  );
}

function pbSectionTitle(key: string): string {
  const map: Record<string, string> = {
    ghs_classification: t.chemical.knowledge.ghs,
    hazards: t.chemical.knowledge.hazards,
    safety_measures: t.chemical.knowledge.safety,
    toxicity: t.chemical.knowledge.toxicology,
    regulatory: t.chemical.knowledge.regulatory,
  };
  return map[key] ?? key;
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
