import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { DetailRefresher } from "@/components/DetailRefresher";
import { EntityId } from "@/components/shared/EntityId";
import { EntityNotes } from "@/components/EntityNotes";
import { FollowButton } from "@/components/shared/FollowButton";
import { Molecule } from "@/components/Molecule";
import { ReactionList } from "@/components/ReactionList";
import { ShareButton } from "@/components/ShareButton";
import { SynonymExplorer } from "@/components/SynonymExplorer";
import { cbInFlight } from "@/components/chemicalStatus";
import { isSummary, type EvidenceEntry } from "@/components/chemicalEvidence";
import { apiGet, isApiNotFound, type Chemical, type ReactionSummary, type SemanticDetail } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag, localizedAbsoluteUrl } from "@/lib/alternates";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

/**
 * Chemical Detail — semantic-first (Design System v2, Issue #4; E9-B 后端合流)。
 *
 * 一级 IA = 语义主题, 来源只是 evidence:
 *   Overview → Names & Identifiers → Properties → Safety & Regulatory
 *   → Chemistry & Industry → Reactions
 * 硬约束: 不为视觉整合发明数据合并; CB/PB 各自保留原值与来源。
 *
 * E9-B: semantic 组合已下沉后端(enrich=full), 页面只做 presentation;
 * 数据请求 = chemical full + reactions(不再请求 /externals)。
 */

const SYN_PREVIEW = 10; // Names 默认展示条数(8–12 区间取 10)

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const canonical = `/chemical/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  // metadata 只需要 canonical 投影 —— enrich=core(零 provider 访问, E9-B 1.6)
  const chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=core`).catch(() => null);
  // 与页面 H1 同源: 同一 resolver、同一 locale, 不允许 SEO 自己再写一套 fallback
  const { title: displayName } = resolveChemicalName({ ...(chemical ?? {}), id }, t.common.hcidLabel, locale);
  const pageTitle = `${displayName} (HCID ${id})`;
  const description = t.chemical.descFor(displayName);
  return {
    title: pageTitle,
    description,
    alternates: localeAlternates(canonical, locale),
    openGraph: {
      url: withLocale(canonical, locale),
      title: `${pageTitle}｜${t.brand.name}`,
      description,
      locale: ogLocaleTag(locale),
      images: [{ url: `/api/mol/${id}/png`, width: 500, height: 375, alt: t.chemical.structureAlt(displayName) }],
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
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const hasSession = (await cookies()).has("hgs_session");
  // 0902 P0: SSR 透传用户凭证(详情页 QPS 低可接受, 沿用)
  const sessionHeaders = hasSession
    ? { cookie: `hgs_session=${(await cookies()).get("hgs_session")?.value ?? ""}` }
    : undefined;

  const [chemicalResult, reactionsResult] = await Promise.all([
    apiGet<Chemical>(`/chemicals/${id}?enrich=full&locale=${encodeURIComponent(locale)}`, sessionHeaders).catch((error: unknown) => {
      if (isApiNotFound(error)) notFound();
      throw error;
    }),
    apiGet<{ total: number; page: number; page_size: number; reactions: ReactionSummary[] }>(
      `/chemicals/${id}/reactions?page=1&page_size=8&role=any`,
    ).catch(() => null),
  ]);
  const chemical = chemicalResult;
  const reactionsUnavailable = reactionsResult === null;
  const initialReactions = reactionsResult?.reactions ?? [];
  const reactionTotal = reactionsResult?.total ?? 0;

  const detail: SemanticDetail | null = chemical.details ?? null;
  const enrichment = chemical.enrichment ?? { status: "current" as const };

  // 内部补全在途判定(不再向 UI 暴露数据源状态): 统一 enrichment queued → 轮询。
  // 空数据不算在途, 否则 fresh negative 会被持续轮询。
  const refreshActive = enrichment.status === "queued" || cbInFlight(detail?.provenance.cb.state);

  // 名称解析唯一出口(与搜索结果/SEO 同规则); pb.record_title 不再入链 ——
  // 数据事实: PubChem 摄入时 preferred_name = properties.Title or record_title,
  // 抽样 6/6 record_title 与 preferred_name 同值, 单独入链只会制造第二套 fallback。
  const { title, secondary } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  const identifiers = identifierGroups(chemical);

  // Names: synonyms(主源) + CB aliases 视觉去重(仅展示层, 不写回)
  const synonyms = chemical.synonyms || [];
  const synTotal = chemical.synonym_count || 0;
  const names = detail?.names;
  const cbIdentity = names?.cb_identity ?? {};
  // 名称别名 union(仅展示层): identical string 只显示一次; CB aliases 并入同一条流,
  // 不再因 synonyms 占满 preview 而被丢弃 —— 展开区可见全部。
  const synLower = new Set(synonyms.map((s) => s.trim().toLowerCase()));
  const cbAliasOnly = (names?.cb_aliases ?? []).map((a) => a.value).filter((a) => !synLower.has(a.trim().toLowerCase()));
  const aliasUnion: { value: string; source: "syn" | "cb" }[] = [
    ...synonyms.map((v) => ({ value: v, source: "syn" as const })),
    ...cbAliasOnly.map((v) => ({ value: v, source: "cb" as const })),
  ];
  const previewAliases = aliasUnion.slice(0, SYN_PREVIEW);
  const synShownInPreview = previewAliases.filter((a) => a.source === "syn").length;
  const cbRest = aliasUnion.slice(SYN_PREVIEW).filter((a) => a.source === "cb");
  const hasAliasRest = aliasUnion.length > SYN_PREVIEW;

  // semantic sections(presentation 分组, 数据已在后端定型)
  const props = detail?.properties;
  const safety = detail?.safety;
  const industry = detail?.industry;
  const pbComputed = props?.pb_computed;
  const hasComputed = Boolean(pbComputed && Object.keys(pbComputed).length > 0);
  const pbPhysical = evidenceEntries(props?.pb_physical_properties);
  const hasProperties = hasComputed || (props?.cb_experimental?.length ?? 0) > 0
    || (props?.cb_prose?.length ?? 0) > 0 || pbPhysical.length > 0;
  const pbSafetySections = safety?.pb_sections ?? {};
  const hasSafetyReal = Object.keys(pbSafetySections).some((k) => evidenceEntries(pbSafetySections[k]).length > 0)
    || Object.keys(safety?.cb_safety ?? {}).length > 0
    || (safety?.cb_toxicity?.length ?? 0) > 0 || (safety?.cb_packaging?.length ?? 0) > 0;
  const pbIndustrySections = industry?.pb_sections ?? {};
  const hasIndustry = (industry?.cb_uses?.length ?? 0) > 0 || (industry?.cb_preparation?.length ?? 0) > 0
    || (industry?.cb_updown?.up?.length ?? 0) > 0 || (industry?.cb_updown?.down?.length ?? 0) > 0
    || (industry?.cb_price?.length ?? 0) > 0 || (detail?.suppliers.items.length ?? 0) > 0
    || (industry?.cb_notes?.length ?? 0) > 0
    || Object.keys(pbIndustrySections).some((k) => evidenceEntries(pbIndustrySections[k]).length > 0);

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
    ...(chemical.pubchem_cid ? { url: localizedAbsoluteUrl(`/chemical/${chemical.id}`, locale) } : {}),
  };

  // TOC 只列实际渲染的 section(rail TOC 与 tablet/mobile local nav 共用此唯一列表)
  const tocSections: [string, string][] = [
    ["overview", t.chemical.page.overview],
    ["names", t.chemical.page.names],
    ...(hasProperties ? [["properties", t.chemical.page.properties] as [string, string]] : []),
    ...(hasSafetyReal ? [["safety", t.chemical.page.safety] as [string, string]] : []),
    ...(hasIndustry ? [["industry", t.chemical.page.industry] as [string, string]] : []),
    ["reactions", t.chemical.relatedReactions],
    ["linked-notes", t.notes.linkedTitle],
  ];

  return (
    <div className="content-page chemical-page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029") }} />
      <nav className="breadcrumbs" aria-label={t.common.breadcrumb}><Link href={withLocale("/", locale)}>{t.chemical.home}</Link><span>/</span><span>{t.chemical.detail}</span></nav>

      {/* ── Chemical Entity Header ── */}
      <header className="chemical-identity">
        <div className="chemical-structure"><Molecule chemicalId={chemical.id} label={title} width={360} height={280} alt={t.chemical.structureAlt(title)} /></div>
        <div className="chemical-title-block">
          <EntityId kind="chemical" id={chemical.id} ariaLabel={t.common.hcidLabel(chemical.id)} />
          <h1>{title}</h1>
          {secondary && <p className="iupac-name">{secondary}</p>}
          {chemical.iupac_name && chemical.iupac_name.toLowerCase() !== title.toLowerCase()
            && chemical.iupac_name.toLowerCase() !== (secondary || "").toLowerCase()
            && <p className="iupac-name">{chemical.iupac_name}</p>}
          <div className="identity-primary">
            {chemical.molecular_formula && <span>{chemical.molecular_formula}</span>}
            {chemical.average_mass != null && <span>{formatNumber(chemical.average_mass, locale)} g/mol</span>}
            {chemical.cas_numbers[0] && <span>CAS {chemical.cas_numbers[0]}</span>}
          </div>
          <div className="context-actions">
            <FollowButton endpoint={`/chemicals/${chemical.id}/follow`} initial={Boolean(chemical.is_following)} count={chemical.follower_count || 0} label="favor" />
            <ShareButton title={title} />
          </div>
          <div className="context-secondary-actions">
            {hasSession ? (chemical.smiles ? (<>
              <Link className="text-button" href={withLocale(`/search?q=${encodeURIComponent(chemical.smiles)}&mode=substructure`, locale)}>{t.chemical.substructure}</Link>
              <Link className="text-button" href={withLocale(`/search?q=${encodeURIComponent(chemical.smiles)}&mode=similarity`, locale)}>{t.chemical.similarity}</Link>
            </>) : null) : (
              <Link className="text-button" href={withLocale(`/login?next=${encodeURIComponent(`/chemical/${chemical.id}`)}`, locale)}>{t.chemical.structureLogin}</Link>
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
            {detail?.description.record_description && <div className="description-panel"><p>{detail.description.record_description}</p></div>}
            <DetailRefresher active={refreshActive} />
            <dl className="identity-table">
              <Identity label={t.chemical.identity.standardSmiles} value={chemical.smiles} mono />
              <Identity label="InChIKey" value={chemical.inchikey} mono />
              <Identity label={t.chemical.identity.formula} value={chemical.molecular_formula} />
              <Identity label={t.chemical.identity.avgMass} value={chemical.average_mass != null ? `${formatNumber(chemical.average_mass, locale)} g/mol` : null} />
              <Identity label={t.chemical.identity.monoMass} value={chemical.monoisotopic_mass != null ? formatNumber(chemical.monoisotopic_mass, locale, 8) : null} />
            </dl>
          </section>

          {/* ── 2. Names & Identifiers ── */}
          <section className="chem-section" id="names">
            <SectionHead anchor="names" eyebrow="NAMES" title={t.chemical.page.names} />
            <dl className="identity-table">
              <Identity label={t.chemical.names.preferred} value={chemical.preferred_name} />
              <Identity label="IUPAC" value={chemical.iupac_name} />
              {cbIdentity.cn ? <Identity label={locale === "zh-CN" ? t.chemical.identity.nameCn : t.chemical.identity.localName} value={String(cbIdentity.cn)} /> : null}
              {cbIdentity.en ? <Identity label={t.chemical.identity.nameEn} value={String(cbIdentity.en)} /> : null}
              {cbIdentity.formula ? <Identity label={t.chemical.identity.formula} value={String(cbIdentity.formula)} /> : null}
              {cbIdentity.mw != null ? <Identity label={t.chemical.identity.molecularWeight} value={String(cbIdentity.mw)} /> : null}
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
              {hasComputed && pbComputed && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.knowledge.descriptors}{enrichment.status !== "current" && enrichment.status !== "degraded" && <span className="chem-subhead-note">{enrichment.status === "stale" ? t.chemical.page.statusStale : t.chemical.page.statusQueued}</span>}</h3>
                  <dl className="metric-grid">
                    <Metric label="XLogP" value={pbComputed.xlogp} locale={locale} />
                    <Metric label={t.chemical.knowledge.tpsa} value={pbComputed.topological_polar_surface_area} suffix=" Å²" locale={locale} />
                    <Metric label={t.chemical.knowledge.hbd} value={pbComputed.hbond_donor_count} locale={locale} />
                    <Metric label={t.chemical.knowledge.hba} value={pbComputed.hbond_acceptor_count} locale={locale} />
                    <Metric label={t.chemical.knowledge.rotatable} value={pbComputed.rotatable_bond_count} locale={locale} />
                    <Metric label={t.chemical.knowledge.heavyAtoms} value={pbComputed.heavy_atom_count} locale={locale} />
                    <Metric label={t.chemical.knowledge.charge} value={pbComputed.formal_charge} locale={locale} />
                    <Metric label={t.chemical.knowledge.complexity} value={pbComputed.complexity} locale={locale} />
                  </dl>
                </div>
              )}
              {pbPhysical.length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.knowledge.experimental}</h3>
                  <EvidenceList entries={pbPhysical} />
                </div>
              )}
              {(props?.cb_experimental?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.props}</h3>
                  <dl className="identity-table">
                    {(props?.cb_experimental ?? []).map((p) => <div key={`${p.label}-${p.text?.slice(0, 12)}`}><dt>{p.label}</dt><dd>{p.v != null ? `${p.v}${p.unit ? ` ${p.unit}` : ""} · ${p.text}` : p.text}</dd></div>)}
                  </dl>
                </div>
              )}
              {(props?.cb_prose?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.chemicalProps}</h3>
                  <ProseList prose={props?.cb_prose ?? []} />
                </div>
              )}
            </section>
          )}

          {/* ── 4. Safety & Regulatory ── */}
          {hasSafetyReal && (
            <section className="chem-section" id="safety">
              <SectionHead anchor="safety" eyebrow="SAFETY" title={t.chemical.page.safety} />
              {Object.entries(pbSafetySections).map(([key, block]) => evidenceEntries(block).length > 0 ? (
                <div className="chem-sub-block" key={key}>
                  <h3 className="chem-subhead">{pbSectionTitle(key, t)}</h3>
                  <EvidenceList entries={evidenceEntries(block)} />
                </div>
              ) : null)}
              {safety?.cb_safety && Object.keys(safety.cb_safety).length > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.safety}</h3>
                  <dl className="identity-table">
                    {Object.entries(safety.cb_safety).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
                  </dl>
                </div>
              )}
              {(safety?.cb_toxicity?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.toxicity}</h3>
                  <ProseList prose={safety?.cb_toxicity ?? []} />
                </div>
              )}
              {(safety?.cb_packaging?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.packaging}</h3>
                  <ProseList prose={safety?.cb_packaging ?? []} />
                </div>
              )}
            </section>
          )}

          {/* ── 5. Chemistry & Industry ── */}
          {hasIndustry && (
            <section className="chem-section" id="industry">
              <SectionHead anchor="industry" eyebrow="INDUSTRY" title={t.chemical.page.industry} />
              {Object.entries(pbIndustrySections).map(([key, block]) => evidenceEntries(block).length > 0 ? (
                <div className="chem-sub-block" key={key}>
                  <h3 className="chem-subhead">{pbSectionTitle(key, t)}</h3>
                  <EvidenceList entries={evidenceEntries(block)} />
                </div>
              ) : null)}
              {(industry?.cb_uses?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.uses}</h3>
                  <ProseList prose={industry?.cb_uses ?? []} />
                </div>
              )}
              {(industry?.cb_preparation?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.preparation}</h3>
                  <ProseList prose={industry?.cb_preparation ?? []} />
                </div>
              )}
              {(industry?.cb_updown?.up?.length ?? 0) > 0 || (industry?.cb_updown?.down?.length ?? 0) > 0 ? (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.updown}</h3>
                  <div className="casext-updown">
                    {(["up", "down"] as const).map((dir) => {
                      const items = dir === "up" ? industry?.cb_updown?.up : industry?.cb_updown?.down;
                      if (!items?.length) return null;
                      return <div key={dir}><h4>{dir === "up" ? t.chemical.casext.upstream : t.chemical.casext.downstream}</h4><div className="casext-tags">{items.map((n) => <span key={`${dir}-${n.name}`} className="casext-tag">{n.name}</span>)}</div></div>;
                    })}
                  </div>
                </div>
              ) : null}
              {(industry?.cb_price?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.price}</h3>
                  <dl className="identity-table">
                    {(industry?.cb_price ?? []).map((r) => <div key={`${r.code}-${r.package}`}><dt>{`${r.code} · ${r.package}`}</dt><dd>{`${r.name} — ${r.price}`}</dd></div>)}
                  </dl>
                </div>
              )}
              {(detail?.suppliers.items.length ?? 0) > 0 && (
                <div className="chem-sub-block" id="suppliers">
                  <h3 className="chem-subhead">{t.chemical.casext.suppliers} <span className="chem-subhead-note">{new Intl.NumberFormat(locale).format(detail?.suppliers.items.length ?? 0)} {t.chemical.casext.supplierUnit}</span></h3>
                  <div className="casext-suppliers">
                    {(detail?.suppliers.items ?? []).map((s) => <SupplierCard key={s.ref} supplier={s} labels={t} />)}
                  </div>
                </div>
              )}
              {(industry?.cb_notes?.length ?? 0) > 0 && (
                <div className="chem-sub-block">
                  <h3 className="chem-subhead">{t.chemical.casext.safetyNotes}</h3>
                  <ProseList prose={industry?.cb_notes ?? []} />
                </div>
              )}
            </section>
          )}

          {/* ── 6. Reactions ── */}
          <section className="chem-section" id="reactions">
            <SectionHead anchor="reactions" eyebrow="REACTIONS" title={t.chemical.relatedReactions}
              note={!reactionsUnavailable ? t.chemical.reactionCount(new Intl.NumberFormat(locale).format(reactionTotal)) : undefined} />
            {reactionsUnavailable ? <p className="quiet-empty">{t.chemical.errReactions}</p> : <ReactionList chemicalId={chemical.id} initial={initialReactions} initialTotal={reactionTotal} />}
          </section>

          <EntityNotes entity="chemical" entityId={chemical.id} canAdd={hasSession} />

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
            <Link href={withLocale(`/submit?chemical=${chemical.id}`, locale)} rel="nofollow">{t.chemical.newReaction}</Link>
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

function Metric({ label, value, suffix = "", locale }: { label: string; value: number | null | undefined; suffix?: string; locale: string }) {
  if (value == null) return null;
  return <div><dt>{label}</dt><dd>{new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(value)}{suffix}</dd></div>;
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

function SupplierCard({ supplier, labels }: { supplier: { ref: string; name: string; phone: string | null; email: string | null; website: string | null; purity: string | null; pack_price: string | null; remark: string | null }; labels: Dictionary }) {
  const { name, phone, email, website, purity, pack_price, remark } = supplier;
  return (
    <article className="casext-supplier">
      <header><h3>{name}</h3></header>
      <dl>
        {purity && <div><dt>{labels.chemical.casext.purity}</dt><dd>{purity}</dd></div>}
        {pack_price && <div><dt>{labels.chemical.casext.packPrice}</dt><dd>{pack_price}</dd></div>}
        {phone && <div><dt>{labels.chemical.casext.phone}</dt><dd>{phone}</dd></div>}
        {email && <div><dt>{labels.chemical.casext.email}</dt><dd>{email}</dd></div>}
        {website && (
          <div><dt>{labels.chemical.casext.website}</dt><dd>
            <a href={website.startsWith("http") ? website : `https://${website}`} target="_blank" rel="nofollow noopener noreferrer">{website}</a>
          </dd></div>
        )}
        {remark && <div><dt>{labels.chemical.casext.remark}</dt><dd>{remark}</dd></div>}
      </dl>
    </article>
  );
}

/** PB evidence block → 展示 entries(presentation-only; 数据形状由后端定型)。 */
function evidenceEntries(block: unknown): EvidenceEntry[] {
  if (!block || typeof block !== "object") return [];
  const record = block as Record<string, unknown>;
  const source = record.entries && typeof record.entries === "object"
    ? record.entries as Record<string, unknown> : record;
  return Object.entries(source)
    .filter(([key]) => !["references", "normalization"].includes(key))
    .map(([path, values]) => ({ label: path.split(" > ").at(-1) || path, values: displayValues(values) }))
    .filter((e) => e.values.length > 0);
}

function displayValues(input: unknown): string[] {
  const list = Array.isArray(input) ? input : [input];
  const result: string[] = [];
  for (const item of list) {
    if (item == null) continue;
    if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
      result.push(String(item)); continue;
    }
    if (typeof item === "object") {
      const record = item as Record<string, unknown>;
      const raw = record.value ?? record.name ?? record.description ?? record.text;
      if (Array.isArray(raw)) result.push(raw.map((value) => scalar(value)).filter(Boolean).join("；"));
      else if (raw != null) result.push(scalar(raw));
    }
  }
  return result.filter(Boolean);
}

function scalar(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.StringWithMarkup && Array.isArray(record.StringWithMarkup)) {
      return record.StringWithMarkup.map((item) => scalar((item as Record<string, unknown>)?.String)).filter(Boolean).join(" ");
    }
  }
  return "";
}

function pbSectionTitle(key: string, labels: Dictionary): string {
  const map: Record<string, string> = {
    "ghs_classification": labels.chemical.knowledge.ghs,
    hazards: labels.chemical.knowledge.hazards,
    safety_measures: labels.chemical.knowledge.safety,
    toxicity: labels.chemical.knowledge.toxicology,
    regulatory: labels.chemical.knowledge.regulatory,
    pharmacology: labels.chemical.knowledge.pharmacology,
    uses_and_manufacturing: labels.chemical.knowledge.uses,
  };
  return map[key] ?? key;
}

function formatNumber(value: number, locale: string, digits = 4) {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
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
