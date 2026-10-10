import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { ChemicalActions } from "@/components/ChemicalActions";
import { ChemPageNav } from "@/components/ChemPageNav";
import { DataRow } from "@/components/DataRow";
import { DetailRefresher } from "@/components/DetailRefresher";
import { GroupToggle } from "@/components/GroupToggle";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { EntityNotes } from "@/components/EntityNotes";
import { Button } from "@/components/ui/Button";
import { CodeField } from "@/components/ui/CodeField";
import { Tag } from "@/components/ui/Tag";
import { Molecule } from "@/components/Molecule";
import { ReactionList } from "@/components/ReactionList";
import { SynonymExplorer } from "@/components/SynonymExplorer";
import { cbInFlight } from "@/components/chemicalStatus";
import { isSummary, type EvidenceEntry } from "@/components/chemicalEvidence";
import { apiGet, isApiNotFound, type Chemical, type ReactionSummary, type SemanticDetail, type ProseItem, type CasSupplier } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag, localizedAbsoluteUrl } from "@/lib/alternates";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

/**
 * Chemical Detail — semantic-first（DESIGN_SYSTEM §9.1 v1.7 Step 6/7 重排）。
 *
 * 一级 IA = 语义主题；分区内按来源分组（组头一行：组标题 + Tag src；
 * v1.7 不做跨来源同名属性合并）。篇幅收敛（Step 7）：每个 h3 组默认
 * 只显示前 6 项（DataRow/已折叠 details 均算 1 项），超出的项服务端
 * hidden + data-overflow（DOM 保留），GroupToggle 客户端翻转；供应商
 * 紧凑行默认 5 家；上下游 Tag 每向最多 12 个。没有内容的分区不渲染，
 * 本页导航同步省略。
 * 硬约束: 只重组展示——数据请求 = chemical full + reactions，不新增不改删。
 */

const SYN_PREVIEW = 12; // Names 默认展示条数（§9.1 前 12 个 Tag）
const COLLAPSE_ITEMS = 2; // 长证据折叠阈值：超过 2 条
const COLLAPSE_CHARS = 240; // 或单条超过 240 字
const GROUP_ITEM_LIMIT = 6; // 组级折叠：h3 组默认可见项数（§9.1 Step 7）
const SUPPLIER_LIMIT = 5; // 供应商默认显示家数
const UPDOWN_TAG_LIMIT = 12; // 上下游 Tag 每向默认显示数

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const canonical = `/chemical/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  // metadata 只需要 canonical 投影 —— enrich=core(零 provider 访问, E9-B 1.6)
  const chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=core`).catch(() => null);
  // 与页面 H1 同源: 同一 resolver、同一 locale, 不允许 SEO 自己再写一套 fallback
  const { title: displayName } = resolveChemicalName({ ...(chemical ?? {}), id }, t.common.hcidLabel, locale);
  const pageTitle = `${displayName} (${t.common.hcidShort(id)})`;
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
  const iupacShow = chemical.iupac_name
    && chemical.iupac_name.toLowerCase() !== title.toLowerCase()
    && chemical.iupac_name.toLowerCase() !== (secondary || "").toLowerCase() ? chemical.iupac_name : null;

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
  const identifiers = identifierGroups(chemical);
  // Names 节只在有实际内容时渲染（种子/本地建行化合物可能全空）。
  // 注意: 这里是"是否有值"的存在性判断, 不是显示名 fallback —— 显示仍走
  // resolveChemicalName 单链（tests/test_chemical_name_resolver 不变量）。
  const hasNames = aliasUnion.length > 0 || identifiers.length > 0 || [
    chemical.preferred_name, chemical.iupac_name, secondary,
    cbIdentity.cn, cbIdentity.en, cbIdentity.formula, cbIdentity.mw,
  ].some((v) => v != null && v !== "");

  // semantic sections(presentation 分组, 数据已在后端定型)
  const props = detail?.properties;
  const safety = detail?.safety;
  const industry = detail?.industry;
  const pbComputed = props?.pb_computed;
  const hasComputed = Boolean(pbComputed && Object.keys(pbComputed).length > 0);
  const pbPhysical = evidenceEntries(props?.pb_physical_properties);
  const hasPbProps = hasComputed || pbPhysical.length > 0;
  const hasCbProps = (props?.cb_experimental?.length ?? 0) > 0 || (props?.cb_prose?.length ?? 0) > 0;
  const hasProperties = hasPbProps || hasCbProps;
  const pbSafetySections = safety?.pb_sections ?? {};
  const hasPbSafety = Object.keys(pbSafetySections).some((k) => evidenceEntries(pbSafetySections[k]).length > 0);
  const hasCbSafety = Object.keys(safety?.cb_safety ?? {}).length > 0
    || (safety?.cb_toxicity?.length ?? 0) > 0 || (safety?.cb_packaging?.length ?? 0) > 0;
  const hasSafetyReal = hasPbSafety || hasCbSafety;
  const pbIndustrySections = industry?.pb_sections ?? {};
  const hasPbIndustry = Object.keys(pbIndustrySections).some((k) => evidenceEntries(pbIndustrySections[k]).length > 0);
  const hasCbIndustry = (industry?.cb_uses?.length ?? 0) > 0 || (industry?.cb_preparation?.length ?? 0) > 0
    || (industry?.cb_updown?.up?.length ?? 0) > 0 || (industry?.cb_updown?.down?.length ?? 0) > 0
    || (industry?.cb_price?.length ?? 0) > 0 || (detail?.suppliers.items.length ?? 0) > 0
    || (industry?.cb_notes?.length ?? 0) > 0;
  const hasIndustry = hasPbIndustry || hasCbIndustry;

  // 记录面板：来源 = 有数据/在途的源；更新 = PubChem 拉取时间；状态 = enrichment
  const recordSources: ("pubchem" | "cb" | "dsstox")[] = ([
    ["pubchem", sourceAlive(detail?.provenance.pubchem.state) || chemical.pubchem_cid != null],
    ["cb", sourceAlive(detail?.provenance.cb.state)],
    ["dsstox", chemical.dtxsid != null],
  ] as ["pubchem" | "cb" | "dsstox", boolean][])
    .filter(([, has]) => has)
    .map(([key]) => key);
  const recordUpdated = detail?.provenance.pubchem.fetched_at ?? null;

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
    ...(hasNames ? [["names", t.chemical.page.names] as [string, string]] : []),
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

      {/* ── Entity Header（§9.1：左内容 + 右 300 结构图卡片） ── */}
      <header className="chem-head">
        <EntityBadge kind="chemical" id={chemical.id} size="lg" copyable ariaLabel={t.common.hcidLabel(chemical.id)} />
        <h1 className="chem-head-name">{title}</h1>
        {secondary && <p className="chem-head-alt">{secondary}</p>}
        {iupacShow && <p className="chem-head-iupac">{iupacShow}</p>}
        <div className="chem-head-chips">
          {chemical.molecular_formula && <Tag>{chemical.molecular_formula}</Tag>}
          {chemical.average_mass != null && <Tag>{formatNumber(chemical.average_mass, locale)} g/mol</Tag>}
          {chemical.cas_numbers[0] && <Tag>CAS {chemical.cas_numbers[0]}</Tag>}
          {chemical.pubchem_cid != null && <Tag>PubChem CID {chemical.pubchem_cid}</Tag>}
        </div>
        <ChemicalActions
          chemicalId={chemical.id}
          smiles={chemical.smiles}
          initialFollowing={Boolean(chemical.is_following)}
          initialCount={chemical.follower_count || 0}
          authed={hasSession}
          title={title}
        />
        <figure className="chem-head-struct">
          <Molecule chemicalId={chemical.id} label={title} width={276} height={206} alt={t.chemical.structureAlt(title)} />
          <figcaption>RDKit 2D</figcaption>
        </figure>
      </header>

      {/* 补全中（enrichment queued / CB 在途）：头部下方 Notice + 原轮询逻辑 */}
      <DetailRefresher active={refreshActive} />

      {/* ── ≤900 顶部横向 Tabs（桌面由右侧栏承担导航） ── */}
      <ChemPageNav sections={tocSections} variant="tabs" />

      <div className="chemical-layout">
        <main className="chemical-main">

          {/* ── 1. Overview ── */}
          <section className="chem-section" id="overview">
            <SectionHead title={t.chemical.page.overview} />
            {detail?.description.record_description && <div className="description-panel"><p>{detail.description.record_description}</p></div>}
            <dl className="chem-dl">
              <DataRow label={t.chemical.identity.standardSmiles}>
                {chemical.smiles && <CodeField value={chemical.smiles} copyLabel={`${t.common.copy} SMILES`} />}
              </DataRow>
              <DataRow label="InChIKey">
                {chemical.inchikey && <CodeField value={chemical.inchikey} copyLabel={`${t.common.copy} InChIKey`} />}
              </DataRow>
              <DataRow label={t.chemical.identity.formula} value={chemical.molecular_formula} />
              <DataRow label={t.chemical.identity.avgMass} value={chemical.average_mass != null ? `${formatNumber(chemical.average_mass, locale)} g/mol` : null} />
              <DataRow label={t.chemical.identity.monoMass} value={chemical.monoisotopic_mass != null ? formatNumber(chemical.monoisotopic_mass, locale, 8) : null} />
            </dl>
          </section>

          {/* ── 2. Names & Identifiers ── */}
          {hasNames && (
          <section className="chem-section" id="names">
            <SectionHead title={t.chemical.page.names} />
            <dl className="chem-dl">
              <DataRow label={t.chemical.names.preferred} value={chemical.preferred_name} />
              <DataRow label="IUPAC" value={chemical.iupac_name} />
              {cbIdentity.cn ? <DataRow label={locale === "zh-CN" ? t.chemical.identity.nameCn : t.chemical.identity.localName} value={String(cbIdentity.cn)} /> : null}
              {cbIdentity.en ? <DataRow label={t.chemical.identity.nameEn} value={String(cbIdentity.en)} /> : null}
              {cbIdentity.formula ? <DataRow label={t.chemical.identity.formula} value={String(cbIdentity.formula)} /> : null}
              {cbIdentity.mw != null ? <DataRow label={t.chemical.identity.molecularWeight} value={String(cbIdentity.mw)} /> : null}
            </dl>
            {(synTotal > 0 || cbAliasOnly.length > 0) && (
              <div className="chem-names-block">
                {/* 不显示 aggregate 总数: 视觉列表是 synonyms + CB aliases 去重 union, 无可靠 union total */}
                <h3 className="chem-subhead">{t.chemical.synonyms.title}</h3>
                <div className="alias-list">
                  {previewAliases.map((a) => <Tag key={`${a.source}-${a.value}`}>{a.value}</Tag>)}
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
                <dl className="chem-dl">
                  {identifiers.map(([label, values]) => <DataRow key={label} label={label} value={values.join("、")} />)}
                </dl>
              </div>
            )}
          </section>
          )}

          {/* ── 3. Properties（分区内按来源分组；组头一行 + 组级折叠） ── */}
          {hasProperties && (
            <section className="chem-section" id="properties">
              <SectionHead title={t.chemical.page.properties} />
              {hasComputed && pbComputed && (
                <ChemGroup gid="grp-prop-descriptors" title={t.chemical.knowledge.descriptors} source="PubChem" total={8} dict={t}
                  note={enrichment.status !== "current" && enrichment.status !== "degraded" ? (enrichment.status === "stale" ? t.chemical.page.statusStale : t.chemical.page.statusQueued) : undefined}>
                  <dl className="chem-dl">
                    {([
                      ["XLogP", fmt(pbComputed.xlogp, locale)],
                      [t.chemical.knowledge.tpsa, pbComputed.topological_polar_surface_area != null ? `${fmt(pbComputed.topological_polar_surface_area, locale)} Å²` : null],
                      [t.chemical.knowledge.hbd, fmt(pbComputed.hbond_donor_count, locale)],
                      [t.chemical.knowledge.hba, fmt(pbComputed.hbond_acceptor_count, locale)],
                      [t.chemical.knowledge.rotatable, fmt(pbComputed.rotatable_bond_count, locale)],
                      [t.chemical.knowledge.heavyAtoms, fmt(pbComputed.heavy_atom_count, locale)],
                      [t.chemical.knowledge.charge, fmt(pbComputed.formal_charge, locale)],
                      [t.chemical.knowledge.complexity, fmt(pbComputed.complexity, locale)],
                    ] as [string, string | null][]).map(([label, value], i) => (
                      <DataRow key={label} label={label} value={value} over={i >= GROUP_ITEM_LIMIT} />
                    ))}
                  </dl>
                </ChemGroup>
              )}
              {pbPhysical.length > 0 && (
                <ChemGroup gid="grp-prop-experimental" title={t.chemical.knowledge.experimental} source="PubChem" total={pbPhysical.length} dict={t}>
                  <EvidenceList entries={pbPhysical} source="PubChem" dict={t} limit={GROUP_ITEM_LIMIT} />
                </ChemGroup>
              )}
              {(props?.cb_experimental?.length ?? 0) > 0 && (
                <ChemGroup gid="grp-prop-cb" title={t.chemical.casext.props} source="ChemicalBook" total={(props?.cb_experimental ?? []).length} dict={t}>
                  <dl className="chem-dl">
                    {(props?.cb_experimental ?? []).map((p, i) => (
                      <DataRow key={`${p.label}-${p.text?.slice(0, 12)}`} label={p.label ?? ""} value={p.v != null ? `${p.v}${p.unit ? ` ${p.unit}` : ""} · ${p.text}` : p.text} over={i >= GROUP_ITEM_LIMIT} />
                    ))}
                  </dl>
                </ChemGroup>
              )}
              {(props?.cb_prose?.length ?? 0) > 0 && (
                <ProseGroup gid="grp-prop-prose" title={t.chemical.casext.chemicalProps} prose={props?.cb_prose ?? []} source="ChemicalBook" dict={t} />
              )}
            </section>
          )}

          {/* ── 4. Safety & Regulatory ── */}
          {hasSafetyReal && (
            <section className="chem-section" id="safety">
              <SectionHead title={t.chemical.page.safety} />
              {Object.entries(pbSafetySections).map(([key, block]) => {
                const entries = evidenceEntries(block);
                return entries.length > 0 ? (
                  <ChemGroup key={key} gid={`grp-safety-${key}`} title={pbSectionTitle(key, t)} source="PubChem" total={entries.length} dict={t}>
                    <EvidenceList entries={entries} source="PubChem" dict={t} limit={GROUP_ITEM_LIMIT} />
                  </ChemGroup>
                ) : null;
              })}
              {safety?.cb_safety && Object.keys(safety.cb_safety).length > 0 && (
                <ChemGroup gid="grp-safety-cb" title={t.chemical.casext.safety} source="ChemicalBook" total={Object.keys(safety.cb_safety).length} dict={t}>
                  <dl className="chem-dl">
                    {Object.entries(safety.cb_safety).map(([k, v], i) => <DataRow key={k} label={k} value={String(v)} over={i >= GROUP_ITEM_LIMIT} />)}
                  </dl>
                </ChemGroup>
              )}
              {(safety?.cb_toxicity?.length ?? 0) > 0 && (
                <ProseGroup gid="grp-toxicity" title={t.chemical.casext.toxicity} prose={safety?.cb_toxicity ?? []} source="ChemicalBook" dict={t} />
              )}
              {(safety?.cb_packaging?.length ?? 0) > 0 && (
                <ProseGroup gid="grp-packaging" title={t.chemical.casext.packaging} prose={safety?.cb_packaging ?? []} source="ChemicalBook" dict={t} />
              )}
            </section>
          )}

          {/* ── 5. Chemistry & Industry ── */}
          {hasIndustry && (
            <section className="chem-section" id="industry">
              <SectionHead title={t.chemical.page.industry} />
              {Object.entries(pbIndustrySections).map(([key, block]) => {
                const entries = evidenceEntries(block);
                return entries.length > 0 ? (
                  <ChemGroup key={key} gid={`grp-industry-${key}`} title={pbSectionTitle(key, t)} source="PubChem" total={entries.length} dict={t}>
                    <EvidenceList entries={entries} source="PubChem" dict={t} limit={GROUP_ITEM_LIMIT} />
                  </ChemGroup>
                ) : null;
              })}
              {(industry?.cb_uses?.length ?? 0) > 0 && (
                <ProseGroup gid="grp-uses" title={t.chemical.casext.uses} prose={industry?.cb_uses ?? []} source="ChemicalBook" dict={t} />
              )}
              {(industry?.cb_preparation?.length ?? 0) > 0 && (
                <ProseGroup gid="grp-preparation" title={t.chemical.casext.preparation} prose={industry?.cb_preparation ?? []} source="ChemicalBook" dict={t} />
              )}
              {(industry?.cb_updown?.up?.length ?? 0) > 0 || (industry?.cb_updown?.down?.length ?? 0) > 0 ? (
                <div className="chem-group">
                  <h3 className="chem-group-head">{t.chemical.casext.updown}<Tag tone="src">ChemicalBook</Tag></h3>
                  <div className="chem-group-body casext-updown">
                    {(["up", "down"] as const).map((dir) => {
                      const items = dir === "up" ? industry?.cb_updown?.up : industry?.cb_updown?.down;
                      if (!items?.length) return null;
                      return <div key={dir}><h4>{dir === "up" ? t.chemical.casext.upstream : t.chemical.casext.downstream}</h4><UpdownTags gid={`grp-updown-${dir}`} direction={dir} items={items} dict={t} /></div>;
                    })}
                  </div>
                </div>
              ) : null}
              {(industry?.cb_price?.length ?? 0) > 0 && (
                <ChemGroup gid="grp-price" title={t.chemical.casext.price} source="ChemicalBook" total={(industry?.cb_price ?? []).length} dict={t}>
                  <dl className="chem-dl">
                    {(industry?.cb_price ?? []).map((r, i) => <DataRow key={`${r.code}-${r.package}`} label={`${r.code} · ${r.package}`} value={`${r.name} — ${r.price}`} over={i >= GROUP_ITEM_LIMIT} />)}
                  </dl>
                </ChemGroup>
              )}
              {(detail?.suppliers.items.length ?? 0) > 0 && (
                <SupplierList gid="grp-suppliers" items={detail?.suppliers.items ?? []} dict={t} locale={locale} />
              )}
              {(industry?.cb_notes?.length ?? 0) > 0 && (
                <ProseGroup gid="grp-notes" title={t.chemical.casext.safetyNotes} prose={industry?.cb_notes ?? []} source="ChemicalBook" dict={t} />
              )}
            </section>
          )}

          {/* ── 6. Reactions ── */}
          <section className="chem-section" id="reactions">
            <SectionHead title={t.chemical.relatedReactions}
              note={!reactionsUnavailable ? t.chemical.reactionCount(new Intl.NumberFormat(locale).format(reactionTotal)) : undefined} />
            {reactionsUnavailable ? <p className="quiet-empty">{t.chemical.errReactions}</p> : <ReactionList chemicalId={chemical.id} initial={initialReactions} initialTotal={reactionTotal} />}
          </section>

          <EntityNotes entity="chemical" entityId={chemical.id} canAdd={hasSession} privateContext={hasSession ? { chemical: chemical.id } : undefined} />

        </main>

        {/* ── Secondary rail (desktop；≤900 移到正文末尾) ── */}
        <aside className="chemical-aside">
          <ChemPageNav sections={tocSections} variant="rail" />
          <section className="chem-record">
            <h2>{t.chemical.page.record}</h2>
            <dl>
              {recordSources.length > 0 && (
                <div><dt>{t.chemical.page.recordSources}</dt><dd>{recordSources.map((key) => recordSourceName(key)).join(" · ")}</dd></div>
              )}
              {recordUpdated && (
                <div><dt>{t.chemical.page.recordUpdated}</dt><dd>{new Date(recordUpdated).toLocaleDateString(locale)}</dd></div>
              )}
              <div><dt>{t.chemical.page.recordStatus}</dt><dd>
                {enrichment.status === "queued" ? <Tag tone="blue" dot>{t.chemical.page.statusQueued}</Tag>
                  : enrichment.status === "current" ? <Tag tone="ok" dot>{t.chemical.page.statusOk}</Tag>
                  : <Tag tone="warn" dot>{t.chemical.page.statusStale}</Tag>}
              </dd></div>
            </dl>
          </section>
          {/* 新建相关反应（PM 决策保留；Step 7 紧凑版：标题 + 一句说明 + tonal sm 按钮） */}
          <section className="contribute-panel">
            <h2 className="contribute-title">{t.chemical.newRelated}</h2>
            <p>{t.chemical.newRelatedHint}</p>
            <Button variant="tonal" size="sm" href={withLocale(`/submit?chemical=${chemical.id}`, locale)}>{t.chemical.newReaction}</Button>
          </section>
        </aside>
      </div>
    </div>
  );
}

/* ── 小组件 ── */

/** 一级 section 标题：h2 22/600/--ls-heading，右侧可选计数注记（§9.1 v1.7 去 eyebrow） */
function SectionHead({ title, note }: { title: string; note?: string }) {
  return (
    <div className="section-heading chem-section-head">
      <h2>{title}</h2>
      {note && <span>{note}</span>}
    </div>
  );
}

/** DataRow 已提取为共享组件 components/DataRow（§9.1/§9.2 统一数据行） */

/** 组级折叠超限标记（DataRow 以外的元素用） */
function overProps(index: number, limit: number) {
  return index >= limit ? { hidden: true as const, "data-overflow": "" } : {};
}

/**
 * 来源分组（§9.1 Step 7 组头一行）：h3 组标题在前，Tag src 紧跟同一行。
 * 篇幅收敛：total > limit 时渲染 GroupToggle（「展开全部 N 项」/「收起」），
 * 超限项由内容构建方标 data-overflow + hidden（仍在上面的 gid 容器内）。
 */
function ChemGroup({ gid, title, source, total, dict, children, note }: {
  gid: string;
  title: string;
  source: string;
  /** 组内总项数（DataRow/已折叠 details 均算 1 项） */
  total: number;
  dict: Dictionary;
  children: ReactNode;
  note?: string;
}) {
  return (
    <div className="chem-group">
      <h3 className="chem-group-head">{title}<Tag tone="src">{source}</Tag>{note && <span className="chem-subhead-note">{note}</span>}</h3>
      <div className="chem-group-body" id={gid}>{children}</div>
      {total > GROUP_ITEM_LIMIT && (
        <GroupToggle controls={gid} total={total} collapsedLabel={dict.chemical.page.expandAll(total)} expandedLabel={dict.chemical.page.collapse} />
      )}
    </div>
  );
}

/** PB evidence 列表：短数值行直接可见；超过 2 条或单条 >240 字折叠为「条目名 · N 条 · 来源」。
 *  组级折叠：limit 之后的条目（含 details）hidden + data-overflow。 */
function EvidenceList({ entries, source, dict, limit = Infinity }: { entries: EvidenceEntry[]; source: string; dict: Dictionary; limit?: number }) {
  return (
    <div className="evidence-list">
      {entries.map((entry, index) => {
        const over = index >= limit;
        return entry.values.length === 1 && isSummary(entry) ? (
          <div key={`${entry.label}-${index}`} className="evidence-flat" hidden={over || undefined} {...(over ? { "data-overflow": "" } : {})}>
            <span className="k">{entry.label}</span>
            <span className="v">{entry.values[0]}</span>
          </div>
        ) : (
          <details key={`${entry.label}-${index}`} hidden={over || undefined} {...(over ? { "data-overflow": "" } : {})}>
            <summary>{entry.label}<span className="evidence-meta"> · {dict.chemical.page.itemsCount(entry.values.length)} · {source}</span></summary>
            <div>{entry.values.map((value, vi) => <p key={vi}>{value}</p>)}</div>
          </details>
        );
      })}
    </div>
  );
}

/** CB 长文组：组头即折叠 summary（「标题 [来源] · N 条」）；≤2 条且短时平铺 */
function ProseGroup({ gid, title, prose, source, dict }: { gid: string; title: string; prose: ProseItem[]; source: string; dict: Dictionary }) {
  const collapsible = prose.length > COLLAPSE_ITEMS || prose.some((item) => item.text.length > COLLAPSE_CHARS);
  const list = <div className="casext-prose-list">{prose.map((item) => <p key={item.title + item.text.slice(0, 24)}><strong>{item.title}</strong>{item.text}</p>)}</div>;
  if (!collapsible) {
    return (
      <div className="chem-group">
        <h3 className="chem-group-head">{title}<Tag tone="src">{source}</Tag></h3>
        <div className="chem-group-body" id={gid}>{list}</div>
      </div>
    );
  }
  return (
    <details className="chem-group prose-group">
      <summary className="chem-group-head">{title}<Tag tone="src">{source}</Tag><span className="evidence-meta"> · {dict.chemical.page.itemsCount(prose.length)}</span></summary>
      <div className="chem-group-body" id={gid}>{list}</div>
    </details>
  );
}

/** 上下游 Tag 列表：每向最多 UPDOWN_TAG_LIMIT 个，超出 data-overflow + 「展开」 */
function UpdownTags({ gid, direction, items, dict }: { gid: string; direction: string; items: { name: string }[]; dict: Dictionary }) {
  return (
    <div className="casext-tags" id={gid}>
      {items.map((n, i) => <span key={`${direction}-${n.name}`} className="casext-tag" {...overProps(i, UPDOWN_TAG_LIMIT)}>{n.name}</span>)}
      {items.length > UPDOWN_TAG_LIMIT && (
        <GroupToggle controls={gid} total={items.length} collapsedLabel={dict.chemical.page.expandTags} expandedLabel={dict.chemical.page.collapse} />
      )}
    </div>
  );
}

/** 供应商（Step 7 紧凑行）：公司名 + 电话 + 邮箱，默认 5 家，「查看全部 N 家」 */
function SupplierList({ gid, items, dict, locale }: { gid: string; items: CasSupplier[]; dict: Dictionary; locale: string }) {
  return (
    <div className="chem-group">
      <h3 className="chem-group-head">{dict.chemical.casext.suppliers}<Tag tone="src">ChemicalBook</Tag><span className="chem-subhead-note">{new Intl.NumberFormat(locale).format(items.length)} {dict.chemical.casext.supplierUnit}</span></h3>
      <div className="chem-group-body supplier-rows" id={gid}>
        {items.map((s, i) => (
          <div key={s.ref} className="supplier-row" {...overProps(i, SUPPLIER_LIMIT)}>
            <span className="supplier-name">{s.name}</span>
            <span className="supplier-contact">{[s.phone, s.email].filter(Boolean).join(" · ") || "—"}</span>
          </div>
        ))}
      </div>
      {items.length > SUPPLIER_LIMIT && (
        <GroupToggle controls={gid} total={items.length} collapsedLabel={dict.chemical.page.viewAllSuppliers(items.length)} expandedLabel={dict.chemical.page.collapse} />
      )}
    </div>
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

/** 来源「有数据或在途」才进记录面板（none/unavailable 不展示） */
function sourceAlive(state: string | null | undefined): boolean {
  return state === "current" || state === "queued" || state === "stale";
}

function recordSourceName(key: "pubchem" | "cb" | "dsstox"): string {
  return key === "pubchem" ? "PubChem" : key === "cb" ? "ChemicalBook" : "DSSTox";
}

function fmt(value: number | null | undefined, locale: string): string | null {
  if (value == null) return null;
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(value);
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
