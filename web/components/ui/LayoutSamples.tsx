"use client";

/**
 * LayoutSamples — 版式基准预览的四张页面组合（/dev-ui/layout-samples，noindex）。
 *
 * 只用版式件（PageFrame/PageHead/Section/CardPanel/InfoRow/Byline）与现有
 * 原子组件；数据全部来自真实后端（化合物 996 详情、用户发布的公开反应、
 * 真实检索结果、MCP 指南同款文案）。用于视觉基准评审，基准未经确认前这些版式件
 * 不得用于正式页面。
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { apiGet, molSvgUrl, reactionSvgUrl, type Chemical, type NoteItem, type ReactionDetail, type SearchResponse } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { Avatar } from "./Avatar";
import { Breadcrumb } from "./Breadcrumb";
import { Button } from "./Button";
import { Byline } from "./Byline";
import { CardPanel } from "./CardPanel";
import { CodeField } from "./CodeField";
import { EntityBadge } from "./EntityBadge";
import { InfoRow } from "./InfoRow";
import { PageFrame } from "./PageFrame";
import { PageHead } from "./PageHead";
import { Section } from "./Section";
import { Segmented } from "./Segmented";
import { Skeleton } from "./Skeleton";
import { Tag } from "./Tag";
import { TextLink } from "./TextLink";

type SampleKey = "chemical" | "reaction" | "search" | "mcp";

const SAMPLE_TABS: ReadonlyArray<{ value: SampleKey; label: string }> = [
  { value: "chemical", label: "化合物详情" },
  { value: "reaction", label: "反应详情" },
  { value: "search", label: "搜索结果" },
  { value: "mcp", label: "MCP 指南" },
];

/* ── 化合物详情（HCID 996）────────────────────────────────── */

function ChemicalSample() {
  const [chem, setChem] = useState<Chemical | null>(null);
  const [notes, setNotes] = useState<NoteItem[]>([]);
  useEffect(() => {
    apiGet<Chemical>("/chemicals/996?enrich=full&locale=zh-CN").then(setChem).catch(() => setChem(null));
    apiGet<{ items: NoteItem[] }>("/chemicals/996/notes?page=1&page_size=5").then((r) => setNotes(r.items)).catch(() => setNotes([]));
  }, []);
  if (!chem) return <div className="hg-page-frame"><Skeleton variant="card" /></div>;
  const det = chem.details ?? null;
  const computed = det?.properties?.pb_computed ?? null;
  const experimental = (det?.properties?.cb_experimental ?? []).slice(0, 6);
  const ghs = ((det?.safety?.pb_sections?.ghs_classification as { entries?: Record<string, { value: string }[]> } | undefined)
    ?.entries ?? {});
  const ghsValues = Object.values(ghs).flat().slice(0, 4).map((e) => e.value);
  const safety = det?.safety?.cb_safety ?? null;
  const name = chem.name_cn || chem.preferred_name || "HCID 996";
  return (
    <PageFrame>
      <PageHead
        hero
        breadcrumb={[{ label: "首页", href: "/" }, { label: "化合物" }, { label: name }]}
        title={<>{name} <EntityBadge kind="chemical" id={996} size="md" copyable /></>}
        subtitle={chem.iupac_name ?? undefined}
        actions={<>
          <Button variant="primary">关注化合物</Button>
          <Button variant="secondary">分享</Button>
        </>}
      />

      <Section title="结构" description="矢量结构图，显示尺寸由版式决定">
        <CardPanel className="du-sample-structure">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={molSvgUrl(996)} width={560} height={420} alt="" />
        </CardPanel>
      </Section>

      <Section title="名称与标识">
        <CardPanel>
          <InfoRow label="中文名">{name}</InfoRow>
          <InfoRow label="系统命名">{chem.iupac_name ?? "—"}</InfoRow>
          <InfoRow label="分子式" mono>{chem.molecular_formula ?? "—"}</InfoRow>
          <InfoRow label="平均质量">{chem.average_mass != null ? `${chem.average_mass} Da` : "—"}</InfoRow>
          <InfoRow label="单同位素质量">{chem.monoisotopic_mass != null ? `${chem.monoisotopic_mass} Da` : "—"}</InfoRow>
          <InfoRow label="InChIKey" mono>{chem.inchikey ?? "—"}</InfoRow>
          <InfoRow label="CAS 号" mono>{(chem.cas_numbers ?? []).join("、") || "—"}</InfoRow>
          <InfoRow label="PubChem CID" mono>{chem.pubchem_cid ?? "—"}</InfoRow>
        </CardPanel>
      </Section>

      <Section title="性质" description="计算性质与实测物化性质">
        {computed ? (
          <CardPanel>
            <InfoRow label="XLogP">{computed.xlogp ?? "—"}</InfoRow>
            <InfoRow label="拓扑极性表面积">{computed.topological_polar_surface_area ?? "—"} Å²</InfoRow>
            <InfoRow label="氢键供体/受体">{computed.hbond_donor_count ?? "—"} / {computed.hbond_acceptor_count ?? "—"}</InfoRow>
            <InfoRow label="可旋转键">{computed.rotatable_bond_count ?? "—"}</InfoRow>
            <InfoRow label="重原子数">{computed.heavy_atom_count ?? "—"}</InfoRow>
            <InfoRow label="复杂度">{computed.complexity ?? "—"}</InfoRow>
          </CardPanel>
        ) : <CardPanel><Skeleton variant="card" /></CardPanel>}
        {experimental.length > 0 && (
          <CardPanel className="du-sample-stack">
            {experimental.map((e, i) => (
              <InfoRow key={i} label={e.label ?? "—"}>{e.text ?? (e.v != null ? `${e.v}${e.unit ? ` ${e.unit}` : ""}` : "—")}</InfoRow>
            ))}
          </CardPanel>
        )}
      </Section>

      <Section title="安全" description="GHS 分类与储运信息">
        {ghsValues.length > 0 || safety ? (
          <>
            {ghsValues.length > 0 && (
              <CardPanel className="du-sample-ghs">
                {ghsValues.map((v, i) => <Tag key={i} tone={i === 0 ? "err" : "warn"}>{v.length > 46 ? `${v.slice(0, 46)}…` : v}</Tag>)}
              </CardPanel>
            )}
            {safety && (
              <CardPanel>
                {safety["危险性类别"] && <InfoRow label="危险性类别">{safety["危险性类别"]}</InfoRow>}
                {safety["存储类别"] && <InfoRow label="存储类别">{safety["存储类别"]}</InfoRow>}
                {safety["危险品运输编号"] && <InfoRow label="运输编号" mono>{safety["危险品运输编号"]}</InfoRow>}
                {safety["毒性"] && <InfoRow label="急性毒性">{safety["毒性"]}</InfoRow>}
                {safety["职业暴露限值"] && <InfoRow label="职业暴露限值">{safety["职业暴露限值"]}</InfoRow>}
              </CardPanel>
            )}
          </>
        ) : <CardPanel><Skeleton variant="card" /></CardPanel>}
      </Section>

      <Section title="关联笔记" description="社区围绕该化合物的公开笔记">
        {notes.length > 0 ? (
          <div className="du-sample-notes">
            {notes.map((n) => (
              <CardPanel key={n.id} className="du-sample-note">
                <Byline
                  user={{ username: n.username, display_name: n.display_name, avatar_url: n.avatar_url, active: n.active }}
                  time={`发布于 ${new Date(n.created_at).toLocaleDateString("zh-CN")}`}
                />
                <p className="du-sample-note-body">{n.content.length > 120 ? `${n.content.slice(0, 120)}…` : n.content}</p>
              </CardPanel>
            ))}
          </div>
        ) : <CardPanel><Skeleton variant="row" /></CardPanel>}
      </Section>
    </PageFrame>
  );
}

/* ── 反应详情（用户发布的公开反应 + 私有头部示意）────────── */

function ReactionSample() {
  const [rx, setRx] = useState<ReactionDetail | null>(null);
  useEffect(() => {
    apiGet<{ id: number }[]>("/users/hgs_demo/reactions")
      .then((rows) => (rows.length ? apiGet<ReactionDetail>(`/reactions/${rows[0].id}`) : null))
      .then((d) => setRx(d))
      .catch(() => setRx(null));
  }, []);
  if (!rx || !rx.creator) return <div className="hg-page-frame"><Skeleton variant="card" /></div>;
  const date = new Date(rx.created_at).toLocaleDateString("zh-CN");
  const participants = rx.participants ?? [];
  return (
    <PageFrame>
      <PageHead
        hero
        breadcrumb={[{ label: "首页", href: "/" }, { label: "反应" }, { label: `反应 ${rx.id}` }]}
        title={<>{rx.dataset_name === "user_submitted" || !rx.dataset_name ? "用户发布的反应" : rx.dataset_name} <EntityBadge kind="reaction" id={rx.id} size="md" copyable /></>}
        meta={<Byline
          user={{ username: rx.creator.username, display_name: rx.creator.display_name, avatar_url: rx.creator.avatar_url, active: rx.creator.active }}
          time={`发布于 ${date}`}
          size={32}
        />}
        actions={<Button variant="secondary">关注反应</Button>}
      />

      {/* 私有反应头部示意：同样版式，仅标识与署名后的标记不同 */}
      <CardPanel className="du-sample-private-head">
        <p className="du-sample-private-caption">私有反应头部示意（无记录卡片与创建者卡片）</p>
        <PageHead
          hero
          breadcrumb={[{ label: "首页", href: "/" }, { label: "反应" }, { label: `反应 ${rx.id}` }]}
          title={<>{rx.dataset_name === "user_submitted" || !rx.dataset_name ? "用户发布的反应" : rx.dataset_name} <EntityBadge kind="reaction" id={rx.id} size="md" state="private" /></>}
          meta={<Byline
            user={{ username: rx.creator.username, display_name: rx.creator.display_name, avatar_url: rx.creator.avatar_url, active: rx.creator.active }}
            time={`发布于 ${date}`}
            privateMark
            size={32}
          />}
        />
      </CardPanel>

      <Section title="反应方程式">
        <CardPanel className="du-sample-equation">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(rx.id)} width={1200} height={300} alt="" />
        </CardPanel>
      </Section>

      <Section title="参与物" description="反应物、试剂与产物">
        <CardPanel>
          {participants.map((p) => (
            <InfoRow key={p.id} label={p.role ?? "—"}>
              <span className="du-sample-participant">
                <EntityBadge kind="chemical" id={p.id} size="sm" />
                <span>{p.preferred_name ?? p.name_cn ?? ""}</span>
                {p.amount_value != null && <Tag>{p.amount_value} {p.amount_unit ?? ""}</Tag>}
                {p.yield_percent != null && <Tag tone="ok">{p.yield_percent}%</Tag>}
              </span>
            </InfoRow>
          ))}
        </CardPanel>
      </Section>

      <Section title="条件">
        <CardPanel>
          <InfoRow label="温度">{rx.temperature ? `${rx.temperature.value} ${rx.temperature.unit}` : "—"}</InfoRow>
          <InfoRow label="时长">{rx.duration ? `${rx.duration.value} ${rx.duration.unit}` : "—"}</InfoRow>
          <InfoRow label="气氛">{rx.atmosphere ?? "—"}</InfoRow>
          <InfoRow label="pH">{rx.ph != null ? String(rx.ph) : "—"}</InfoRow>
          <InfoRow label="回流">{rx.reflux == null ? "—" : rx.reflux ? "是" : "否"}</InfoRow>
        </CardPanel>
      </Section>

      <Section title="来源">
        <CardPanel>
          <InfoRow label="来源类型">{rx.source_type ?? "—"}</InfoRow>
          <InfoRow label="引用">{rx.source_citation ?? "—"}</InfoRow>
          <InfoRow label="DOI" mono>{rx.doi ?? "—"}</InfoRow>
          <InfoRow label="专利" mono>{rx.patent ?? "—"}</InfoRow>
        </CardPanel>
      </Section>
    </PageFrame>
  );
}

/* ── 搜索结果 ─────────────────────────────────────────────── */

function SearchSample() {
  const [res, setRes] = useState<SearchResponse | null>(null);
  useEffect(() => {
    apiGet<SearchResponse>("/search?q=phenol&mode=exact&page=1&page_size=20").then(setRes).catch(() => setRes(null));
  }, []);
  if (!res) return <div className="hg-page-frame"><Skeleton variant="card" /></div>;
  return (
    <PageFrame>
      <PageHead
        breadcrumb={[{ label: "首页", href: "/" }, { label: "搜索" }]}
        title={`“phenol” 的搜索结果`}
        subtitle={`命中 ${res.chemicals.length} 个化合物`}
      />
      <Section title="化合物">
        <div className="du-sample-notes">
          {res.chemicals.map((c) => (
            <CardPanel key={c.id} className="du-sample-search-card">
              <span className="du-sample-search-title">
                <EntityBadge kind="chemical" id={c.id} size="sm" href={`/chemical/${c.id}`} />
                <TextLink href={`/chemical/${c.id}`}>{c.name_cn || c.preferred_name || `化合物 ${c.id}`}</TextLink>
                {c.molecular_formula && <Tag>{c.molecular_formula}</Tag>}
              </span>
              {c.cas_numbers && c.cas_numbers.length > 0 && (
                <p className="du-sample-note-body">CAS {(c.cas_numbers ?? []).slice(0, 3).join("、")}</p>
              )}
            </CardPanel>
          ))}
        </div>
      </Section>
    </PageFrame>
  );
}

/* ── MCP 指南 ─────────────────────────────────────────────── */

function McpSample() {
  const t = useDictionary();
  return (
    <PageFrame tier="reading">
      <PageHead
        breadcrumb={[{ label: "首页", href: "/" }, { label: t.mcp.hero }]}
        title={t.mcp.hero}
        subtitle={t.mcp.heroBody}
      />

      <Section title={t.mcp.connectKicker} description="连接地址与接入方式">
        <CardPanel className="du-sample-stack">
          <InfoRow label={t.mcp.connectUrlLabel} mono><CodeField value="https://huagongshe.com/mcp" /></InfoRow>
          <InfoRow label={t.mcp.connectAnonLabel}>{t.mcp.connectAnonDesc}</InfoRow>
          <InfoRow label={t.mcp.connectOauthLabel}>{t.mcp.connectOauthDesc}</InfoRow>
          <InfoRow label={t.mcp.connectTokenLabel} mono><CodeField value="Authorization: Bearer <AI Key>" /></InfoRow>
        </CardPanel>
      </Section>

      <Section title={t.mcp.toolsKicker} description={t.mcp.toolsIntro}>
        <CardPanel className="du-sample-stack">
          {t.mcp.tools.map((tool) => (
            <InfoRow key={tool.name} label={<code>{tool.name}</code>}>
              <span className="du-sample-tool">
                <Tag>{tool.auth}</Tag>
                <span>{tool.desc}</span>
              </span>
            </InfoRow>
          ))}
        </CardPanel>
      </Section>

      <Section title={t.mcp.pluginTitle} description={t.mcp.pluginStatus}>
        <CardPanel>
          <Button variant="secondary" href="/downloads/huagongshe-agent-plugin-1.0.0.zip" download>
            {t.mcp.pluginDownload}
          </Button>
        </CardPanel>
      </Section>
    </PageFrame>
  );
}

/* ── 外壳 ─────────────────────────────────────────────────────── */

export function LayoutSamplesClient() {
  const params = useSearchParams();
  const initial = (params.get("sample") as SampleKey) || "chemical";
  const [tab, setTab] = useState<SampleKey>(
    SAMPLE_TABS.some((s) => s.value === initial) ? initial : "chemical",
  );
  return (
    <div className="du-samples">
      <Segmented
        options={SAMPLE_TABS.map((s) => ({ value: s.value, label: s.label }))}
        value={tab}
        onChange={(v) => setTab(v)}
        ariaLabel="页面切换"
      />
      {tab === "chemical" && <ChemicalSample />}
      {tab === "reaction" && <ReactionSample />}
      {tab === "search" && <SearchSample />}
      {tab === "mcp" && <McpSample />}
    </div>
  );
}
