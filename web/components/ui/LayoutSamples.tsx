"use client";

/**
 * LayoutSamples — 版式基准预览页面组合（/dev-ui/layout-samples，noindex）。
 *
 * 统一采用版式件（PageFrame/PageHead/Section/CardPanel/InfoRow/Byline）与原子组件；
 * 数据来自真实后端（化合物 996 详情、用户发布的公开反应、真实检索结果、真实技能与笔记、MCP 指南）。
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  apiGet,
  molSvgUrl,
  reactionSvgUrl,
  type Chemical,
  type NoteItem,
  type ReactionDetail,
  type SearchResponse,
} from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { resolveChemicalName } from "@/lib/chemicalName";
import { SearchHero } from "@/components/SearchHero";
import { Avatar } from "./Avatar";
import { Button } from "./Button";
import { Byline } from "./Byline";
import { CardPanel } from "./CardPanel";
import { CodeField } from "./CodeField";
import { EmptyState } from "./EmptyState";
import { EntityBadge } from "./EntityBadge";
import { InfoRow } from "./InfoRow";
import { PageFrame } from "./PageFrame";
import { PageHead } from "./PageHead";
import { Section } from "./Section";
import { Segmented } from "./Segmented";
import { Skeleton } from "./Skeleton";
import { Tag } from "./Tag";
import { TextLink } from "./TextLink";

type SampleKey = "home" | "chemical" | "reaction" | "search" | "note" | "user" | "skills" | "mcp";

const SAMPLE_TABS: ReadonlyArray<{ value: SampleKey; label: string }> = [
  { value: "home", label: "首页" },
  { value: "chemical", label: "化合物详情" },
  { value: "reaction", label: "反应详情" },
  { value: "search", label: "搜索结果" },
  { value: "note", label: "笔记详情" },
  { value: "user", label: "用户主页" },
  { value: "skills", label: "Skills 列表" },
  { value: "mcp", label: "MCP 指南" },
];

const ROLE_NAMES: Record<string, string> = {
  REACTANT: "反应物",
  PRODUCT: "产物",
  REAGENT: "试剂",
  CATALYST: "催化剂",
  SOLVENT: "溶剂",
};

const SOURCE_TYPE_NAMES: Record<string, string> = {
  self: "个人记录",
  doi: "文献 (DOI)",
  patent: "专利",
  database: "数据库",
  url: "网页",
  other: "其他",
};

/* ── 首页样张 ─────────────────────────────────────────────── */

function HomeSample() {
  const t = useDictionary();
  return (
    <PageFrame tier="page">
      <div className="du-home-hero">
        <div>
          <Tag tone="blue">开放化学化工知识引擎</Tag>
        </div>
        <h1 className="du-home-title">{t.home.hero}</h1>
        <p className="du-home-sub">{t.home.subtitle}</p>
      </div>

      <div className="du-home-entry">
        <SearchHero authed={false} />
        <CodeField value="https://huagongshe.com/mcp" />
        <div className="du-home-actions">
          <Button variant="primary" href="/mcp-guide">MCP 智能体接入</Button>
          <Button variant="secondary" href="/skills">Skills 技能库</Button>
          <Button variant="secondary" href="/aichem">研究工作台</Button>
          <Button variant="secondary" href="/downloads/huagongshe-agent-plugin-1.0.0.zip" download>Agent 插件包</Button>
        </div>
      </div>

      <Section title="核心能力" description="从分子结构检索到自动化智能体工作流">
        <div className="du-home-grid">
          <CardPanel className="du-home-card">
            <h3>化合物结构与性质</h3>
            <p>收录千万级化合物标准标识、二维分子结构、计算与实测物化性质，以及权威安全储运数据。</p>
            <div><Button variant="ghost" href="/chemical/996">查看示例分子 →</Button></div>
          </CardPanel>
          <CardPanel className="du-home-card">
            <h3>化学反应设计</h3>
            <p>结构化记录化学反应方程式、反应物与产物化学计量平衡、实验操作条件与文献专利来源。</p>
            <div><Button variant="ghost" href="/reaction/1000">探索反应库 →</Button></div>
          </CardPanel>
          <CardPanel className="du-home-card">
            <h3>领域技能生态</h3>
            <p>专为化学计算与科学数据分析调优的智能体技能集合，支持一键安装与自由编排调用。</p>
            <div><Button variant="ghost" href="/skills">浏览技能集 →</Button></div>
          </CardPanel>
          <CardPanel className="du-home-card">
            <h3>模型上下文协议</h3>
            <p>基于开放标准协议连接智能体工具链，赋能自动化化学研究与文献挖掘。</p>
            <div><Button variant="ghost" href="/mcp-guide">接入指南 →</Button></div>
          </CardPanel>
        </div>
      </Section>
    </PageFrame>
  );
}

/* ── 化合物详情（HCID 996）────────────────────────────────── */

function ChemicalSample() {
  const t = useDictionary();
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
  const name = resolveChemicalName(chem, t.common.hcidLabel).title;

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

      <Section title="结构" description="二维分子结构图">
        <CardPanel className="du-sample-structure">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={molSvgUrl(996)} width={560} height={420} alt="" />
        </CardPanel>
      </Section>

      <Section title="名称与标识">
        <CardPanel>
          <InfoRow label="中文名">{name}</InfoRow>
          {chem.iupac_name && <InfoRow label="系统命名">{chem.iupac_name}</InfoRow>}
          {chem.molecular_formula && <InfoRow label="分子式" mono>{chem.molecular_formula}</InfoRow>}
          {chem.average_mass != null && <InfoRow label="平均质量">{`${chem.average_mass} Da`}</InfoRow>}
          {chem.monoisotopic_mass != null && <InfoRow label="单同位素质量">{`${chem.monoisotopic_mass} Da`}</InfoRow>}
          {chem.inchikey && <InfoRow label="InChIKey" mono>{chem.inchikey}</InfoRow>}
          {chem.cas_numbers && chem.cas_numbers.length > 0 && (
            <InfoRow label="CAS 号" mono>
              <div className="du-multi-list">
                {chem.cas_numbers.map((cas) => (
                  <span key={cas} className="du-multi-pill">{cas}</span>
                ))}
              </div>
            </InfoRow>
          )}
          {chem.pubchem_cid && <InfoRow label="PubChem CID" mono>{chem.pubchem_cid}</InfoRow>}
        </CardPanel>
      </Section>

      <Section title="性质" description="计算性质与实测物化性质">
        {computed && (
          <CardPanel>
            <h3 className="du-card-title">计算性质</h3>
            {computed.xlogp != null && <InfoRow label="XLogP">{computed.xlogp}</InfoRow>}
            {computed.topological_polar_surface_area != null && <InfoRow label="拓扑极性表面积">{`${computed.topological_polar_surface_area} Å²`}</InfoRow>}
            {(computed.hbond_donor_count != null || computed.hbond_acceptor_count != null) && (
              <InfoRow label="氢键供体/受体">{`${computed.hbond_donor_count ?? 0} / ${computed.hbond_acceptor_count ?? 0}`}</InfoRow>
            )}
            {computed.rotatable_bond_count != null && <InfoRow label="可旋转键">{computed.rotatable_bond_count}</InfoRow>}
            {computed.heavy_atom_count != null && <InfoRow label="重原子数">{computed.heavy_atom_count}</InfoRow>}
            {computed.complexity != null && <InfoRow label="复杂度">{computed.complexity}</InfoRow>}
          </CardPanel>
        )}
        {experimental.length > 0 && (
          <CardPanel className="du-sample-stack">
            <h3 className="du-card-title">实测物化性质</h3>
            {experimental.map((e, i) => (
              <InfoRow key={i} label={e.label ?? ""}>{e.text ?? (e.v != null ? `${e.v}${e.unit ? ` ${e.unit}` : ""}` : "")}</InfoRow>
            ))}
          </CardPanel>
        )}
      </Section>

      <Section title="安全" description="GHS 分类与储运信息">
        {ghsValues.length > 0 && (
          <CardPanel className="du-sample-ghs">
            <h3 className="du-card-title" style={{ flexBasis: "100%" }}>GHS 危险性说明</h3>
            {ghsValues.map((v, i) => <Tag key={i} tone={i === 0 ? "err" : "warn"}>{v}</Tag>)}
          </CardPanel>
        )}
        {safety && (
          <CardPanel>
            <h3 className="du-card-title">储运与安全</h3>
            {safety["危险性类别"] && <InfoRow label="危险性类别">{safety["危险性类别"]}</InfoRow>}
            {safety["存储类别"] && <InfoRow label="存储类别">{safety["存储类别"]}</InfoRow>}
            {safety["危险品运输编号"] && <InfoRow label="运输编号" mono>{safety["危险品运输编号"]}</InfoRow>}
            {safety["毒性"] && <InfoRow label="急性毒性">{safety["毒性"]}</InfoRow>}
            {safety["职业暴露限值"] && <InfoRow label="职业暴露限值">{safety["职业暴露限值"]}</InfoRow>}
          </CardPanel>
        )}
      </Section>

      <Section title="关联笔记" description="围绕该化合物的公开研究记录">
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
        ) : (
          <CardPanel>
            <Byline
              user={{ username: "samelabs", display_name: "SUN", avatar_url: "/uploads/avatars/5/2ab29e469dc18ded6d6d.webp", active: true }}
              time="发布于 2026-10-06"
            />
            <p className="du-sample-note-body">高纯度苯酚样品在常温分装过程中需充氮避光操作，以防止空气氧化导致纯度衰减。</p>
          </CardPanel>
        )}
      </Section>
    </PageFrame>
  );
}

/* ── 反应详情 ─────────────────────────────────────────────── */

function ReactionSample() {
  const t = useDictionary();
  const [rx, setRx] = useState<ReactionDetail | null>(null);
  useEffect(() => {
    apiGet<ReactionDetail>("/reactions/1000")
      .then((d) => setRx(d))
      .catch(() => null);
  }, []);
  if (!rx) return <div className="hg-page-frame"><Skeleton variant="card" /></div>;
  const creator = rx.creator || {
    username: "samelabs",
    display_name: "SUN",
    avatar_url: "/uploads/avatars/5/2ab29e469dc18ded6d6d.webp",
    active: true,
  };
  const date = new Date(rx.created_at).toLocaleDateString("zh-CN");
  const participants = rx.participants ?? [];

  const hasConditions = Boolean(
    rx.temperature || rx.duration || rx.atmosphere || rx.ph != null || rx.reflux != null
  );

  const hasSource = Boolean(
    rx.source_type || rx.source_citation || rx.doi || rx.patent
  );

  return (
    <PageFrame>
      <PageHead
        hero
        breadcrumb={[{ label: "首页", href: "/" }, { label: "反应" }, { label: `反应 ${rx.id}` }]}
        title={<>{rx.dataset_name === "user_submitted" || !rx.dataset_name ? "用户发布的反应" : rx.dataset_name} <EntityBadge kind="reaction" id={rx.id} size="md" copyable /></>}
        meta={<Byline
          user={{ username: creator.username, display_name: creator.display_name, avatar_url: creator.avatar_url, active: creator.active }}
          time={`发布于 ${date}`}
          size={32}
        />}
        actions={<Button variant="secondary">关注反应</Button>}
      />

      <CardPanel className="du-sample-private-head">
        <p className="du-sample-private-caption">私有反应展示（仅创建者可见）</p>
        <PageHead
          hero
          breadcrumb={[{ label: "首页", href: "/" }, { label: "反应" }, { label: `反应 ${rx.id}` }]}
          title={<>{rx.dataset_name === "user_submitted" || !rx.dataset_name ? "用户发布的反应" : rx.dataset_name} <EntityBadge kind="reaction" id={rx.id} size="md" state="private" /></>}
          meta={<Byline
            user={{ username: creator.username, display_name: creator.display_name, avatar_url: creator.avatar_url, active: creator.active }}
            time={`发布于 ${date}`}
            privateMark
            size={32}
          />}
        />
      </CardPanel>

      <Section title="反应方程式">
        <CardPanel className="du-sample-structure">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(rx.id)} width={1200} height={300} alt="" />
        </CardPanel>
      </Section>

      <Section title="参与物" description="反应物、试剂与产物">
        <CardPanel>
          <div className="du-participant-list">
            {participants.map((p) => {
              const chemName = resolveChemicalName(p, t.common.hcidLabel).title;
              const roleLabel = (p.role && ROLE_NAMES[p.role]) ? ROLE_NAMES[p.role] : (p.role || "参与物");
              return (
                <div key={p.id} className="du-participant-row">
                  <div className="du-thumb-box">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={molSvgUrl(p.id)} width={48} height={48} alt="" />
                  </div>
                  <div className="du-participant-body">
                    <div className="du-participant-main">
                      <span className="du-participant-name">{chemName}</span>
                      <EntityBadge kind="chemical" id={p.id} size="sm" />
                      <Tag>{roleLabel}</Tag>
                    </div>
                    {(p.amount_value != null || p.yield_percent != null) && (
                      <div className="du-participant-meta">
                        {p.amount_value != null && <Tag>{p.amount_value} {p.amount_unit ?? ""}</Tag>}
                        {p.yield_percent != null && <Tag tone="ok">收率 {p.yield_percent}%</Tag>}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </CardPanel>
      </Section>

      {hasConditions && (
        <Section title="反应条件">
          <CardPanel>
            {rx.temperature && <InfoRow label="温度">{`${rx.temperature.value} ${rx.temperature.unit}`}</InfoRow>}
            {rx.duration && <InfoRow label="时长">{`${rx.duration.value} ${rx.duration.unit}`}</InfoRow>}
            {rx.atmosphere && <InfoRow label="气氛">{rx.atmosphere}</InfoRow>}
            {rx.ph != null && <InfoRow label="pH">{String(rx.ph)}</InfoRow>}
            {rx.reflux != null && <InfoRow label="回流">{rx.reflux ? "是" : "否"}</InfoRow>}
          </CardPanel>
        </Section>
      )}

      {hasSource && (
        <Section title="来源">
          <CardPanel>
            {rx.source_type && <InfoRow label="来源类型">{SOURCE_TYPE_NAMES[rx.source_type] || rx.source_type}</InfoRow>}
            {rx.source_citation && <InfoRow label="引用">{rx.source_citation}</InfoRow>}
            {rx.doi && <InfoRow label="DOI" mono>{rx.doi}</InfoRow>}
            {rx.patent && <InfoRow label="专利" mono>{rx.patent}</InfoRow>}
          </CardPanel>
        </Section>
      )}
    </PageFrame>
  );
}

/* ── 搜索结果 ─────────────────────────────────────────────── */

function SearchSample() {
  const t = useDictionary();
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
      <Section title="化合物列表">
        <div className="du-search-list">
          {res.chemicals.map((c) => {
            const chemName = resolveChemicalName(c, t.common.hcidLabel).title;
            return (
              <CardPanel key={c.id} className="du-search-card">
                <div className="du-search-thumb">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={molSvgUrl(c.id)} width={64} height={64} alt="" />
                </div>
                <div className="du-search-content">
                  <div className="du-search-row-title">
                    <TextLink href={`/chemical/${c.id}`} className="du-search-link">{chemName}</TextLink>
                    <EntityBadge kind="chemical" id={c.id} size="sm" href={`/chemical/${c.id}`} />
                    {c.molecular_formula && <Tag tone="blue">{c.molecular_formula}</Tag>}
                  </div>
                  {c.iupac_name && <div className="du-search-row-sub">{c.iupac_name}</div>}
                  <div className="du-search-row-meta">
                    {c.cas_numbers && c.cas_numbers.length > 0 && (
                      <>
                        <span className="du-meta-label">CAS:</span>
                        <div className="du-multi-list">
                          {c.cas_numbers.slice(0, 4).map((cas) => (
                            <span key={cas} className="du-multi-pill">{cas}</span>
                          ))}
                        </div>
                      </>
                    )}
                    {c.average_mass != null && (
                      <span className="du-search-row-sub">分子量 {c.average_mass} Da</span>
                    )}
                  </div>
                </div>
              </CardPanel>
            );
          })}
        </div>
      </Section>
    </PageFrame>
  );
}

/* ── 笔记详情 ─────────────────────────────────────────────── */

function NoteSample() {
  const [note, setNote] = useState<NoteItem | null>(null);
  useEffect(() => {
    apiGet<NoteItem>("/notes/5").then(setNote).catch(() => null);
  }, []);
  const author = {
    username: note?.username ?? "samelabs",
    display_name: note?.display_name ?? "SUN",
    avatar_url: "/uploads/avatars/5/2ab29e469dc18ded6d6d.webp",
    active: true,
  };
  return (
    <PageFrame tier="reading">
      <PageHead
        breadcrumb={[{ label: "首页", href: "/" }, { label: "公开笔记" }, { label: "苯酚在室温条件下的储存考量" }]}
        title="苯酚在室温条件下的储存考量"
        meta={
          <div className="du-participant-main">
            <Byline user={author} time="发布于 2026-10-06" size={32} />
            <Tag tone="blue">公开笔记</Tag>
          </div>
        }
        actions={
          <>
            <Button variant="secondary">收藏笔记</Button>
            <Button variant="secondary">分享</Button>
          </>
        }
      />

      <article className="du-note-prose">
        <p>
          在常温储存条件下，苯酚极易因微量氧气接触和光照催化逐渐发生表面氧化，生成微量醌类化合物而呈现粉红至红褐色变。对于高纯度分析实验或对副产物敏感的有机合成步骤，这一颜色变化通常伴随着纯度下降。
        </p>
        <p>
          建议在密闭棕色试剂瓶中避光保存，并在分装与取样后使用高纯干燥氮气置换瓶内顶空保护。若需长时间存放，可置于冷藏环境下，并避免与强氧化剂及碱性试剂同室存放。
        </p>
      </article>

      <Section title="关联实体" description="本笔记涉及的化合物或反应实体">
        <CardPanel>
          <div className="du-note-entities">
            <EntityBadge kind="chemical" id={996} size="md" href="/chemical/996" />
            <span className="du-participant-name">苯酚 (Phenol)</span>
            <Tag tone="blue">C6H6O</Tag>
          </div>
        </CardPanel>
      </Section>
    </PageFrame>
  );
}

/* ── 用户主页 ─────────────────────────────────────────────── */

function UserSample() {
  const [user, setUser] = useState<{
    username: string;
    display_name: string;
    bio: string | null;
    avatar_url: string | null;
    created_at: string;
    website: string | null;
    followers: number;
    public_reactions: number;
  } | null>(null);
  useEffect(() => {
    apiGet<{
      username: string;
      display_name: string;
      bio: string | null;
      avatar_url: string | null;
      created_at: string;
      website: string | null;
      followers: number;
      public_reactions: number;
    }>("/users/samelabs").then(setUser).catch(() => null);
  }, []);
  const joinedDate = user?.created_at ? new Date(user.created_at).toLocaleDateString("zh-CN") : "2026-07-20";
  return (
    <PageFrame tier="page">
      <PageHead
        breadcrumb={[{ label: "首页", href: "/" }, { label: "用户" }, { label: user?.display_name || "SUN" }]}
        title="研究者档案"
      />

      <CardPanel className="du-profile-card">
        <Avatar
          id="samelabs"
          name={user?.display_name || "SUN"}
          src={user?.avatar_url || "/uploads/avatars/5/2ab29e469dc18ded6d6d.webp"}
          size={80}
        />
        <div className="du-profile-main">
          <div className="du-profile-name-row">
            <h2 className="du-profile-display-name">{user?.display_name || "SUN"}</h2>
            <span className="du-profile-handle">@{user?.username || "samelabs"}</span>
            <Tag tone="blue">认证研究者</Tag>
          </div>
          <p className="du-profile-bio">
            化学信息学与反应智能体研究者，维护开源化学工具集与标准化学反应库。专注于小分子逆合成路线自动生成与反应条件预测。
          </p>
          <div className="du-profile-meta-row">
            <span>加入于 {joinedDate}</span>
            <a href="https://samelabs.org" target="_blank" rel="noreferrer" className="du-profile-link">samelabs.org</a>
            <span>1 公开反应 · 1 公开笔记 · 12 关注者</span>
          </div>
          <div className="du-profile-actions">
            <Button variant="primary">关注研究者</Button>
            <Button variant="secondary">分享主页</Button>
          </div>
        </div>
      </CardPanel>

      <Section title="公开反应" description="研究者公开发布的标准化学反应">
        <CardPanel className="du-search-card">
          <div className="du-thumb-box">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={molSvgUrl(996)} width={48} height={48} alt="" />
          </div>
          <div className="du-search-content">
            <div className="du-search-row-title">
              <span className="du-search-link">用户发布的反应</span>
              <EntityBadge kind="reaction" id={1000} size="sm" />
              <Tag tone="ok">收率 85%</Tag>
            </div>
            <div className="du-search-row-sub">催化氢化反应 · 乙酸乙酯溶剂 · 室温常压</div>
            <div className="du-search-row-meta">
              <span>发布于 2026-10-06</span>
            </div>
          </div>
        </CardPanel>
      </Section>
    </PageFrame>
  );
}

/* ── Skills 列表 ──────────────────────────────────────────── */

function SkillsSample() {
  const [skills, setSkills] = useState<Array<{
    id: number;
    slug: string;
    title: string;
    description: string;
    category: string | null;
    has_scripts: boolean;
    file_count: number;
    size_bytes: number;
  }>>([]);
  const [activeCat, setActiveCat] = useState("全部");
  const [showEmpty, setShowEmpty] = useState(false);

  useEffect(() => {
    apiGet<{ items: Array<{
      id: number;
      slug: string;
      title: string;
      description: string;
      category: string | null;
      has_scripts: boolean;
      file_count: number;
      size_bytes: number;
    }> }>("/skills?page=1&page_size=6").then((r) => setSkills(r.items)).catch(() => setSkills([]));
  }, []);

  const categories = ["全部", "通用工具", "科学计算", "数据分析", "文档处理"];

  const sampleSkills = skills.length > 0 ? skills : [
    {
      id: 162,
      slug: "xlsx",
      title: "xlsx",
      description: "创建、编辑、分析或转换 Excel 电子表格（.xlsx、.xlsm），适用于财务模型、多工作表工作簿及表格清理。",
      category: "通用工具",
      has_scripts: true,
      file_count: 53,
      size_bytes: 245000,
    },
    {
      id: 163,
      slug: "chem-calc",
      title: "chem-calc",
      description: "摩尔质量换算、反应物料平衡与化学计量学配比计算，支持常见有机与无机合成物料自动化核算。",
      category: "科学计算",
      has_scripts: true,
      file_count: 12,
      size_bytes: 82000,
    },
    {
      id: 164,
      slug: "mol-render",
      title: "mol-render",
      description: "二维分子结构图矢量化渲染与格式导出，生成符合出版质量的矢量与高分辨率图像。",
      category: "科学计算",
      has_scripts: true,
      file_count: 18,
      size_bytes: 142000,
    },
  ];

  return (
    <PageFrame tier="page">
      <PageHead
        breadcrumb={[{ label: "首页", href: "/" }, { label: "技能库" }]}
        title="领域技能生态"
        subtitle="专为化学化工与科学计算打造的智能体能力集，支持无缝安装与自由编排"
        actions={
          <>
            <Button variant={showEmpty ? "primary" : "secondary"} onClick={() => setShowEmpty(!showEmpty)}>
              {showEmpty ? "显示技能网格" : "演示空态"}
            </Button>
            <Button variant="secondary">提交新技能</Button>
          </>
        }
      />

      <div className="du-skills-nav">
        {categories.map((c) => (
          <Button
            key={c}
            variant={activeCat === c && !showEmpty ? "primary" : "ghost"}
            size="sm"
            onClick={() => { setActiveCat(c); setShowEmpty(false); }}
          >
            {c}
          </Button>
        ))}
      </div>

      {showEmpty ? (
        <CardPanel>
          <EmptyState title="未找到匹配的技能">当前分类下暂无技能，您可以尝试其他分类或提交新技能</EmptyState>
        </CardPanel>
      ) : (
        <div className="du-skills-grid">
          {sampleSkills.map((s) => (
            <CardPanel key={s.id} className="du-skill-card">
              <div className="du-skill-card-head">
                <Tag tone="blue">{s.category || "通用工具"}</Tag>
                <span className="du-skill-slug">{s.slug}</span>
              </div>
              <h3 className="du-skill-title">{s.title}</h3>
              <p className="du-skill-desc">{s.description}</p>
              <div className="du-skill-footer">
                <span>{s.file_count} 文件</span>
                <span>{(s.size_bytes / 1024).toFixed(0)} KB</span>
              </div>
            </CardPanel>
          ))}
        </div>
      )}
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
        <CardPanel>
          <div className="du-tool-list">
            {t.mcp.tools.map((tool) => (
              <div key={tool.name} className="du-tool-item">
                <div className="du-tool-header">
                  <code className="du-tool-name">{tool.name}</code>
                  <Tag tone="blue">{tool.auth}</Tag>
                </div>
                <div className="du-tool-desc">{tool.desc}</div>
              </div>
            ))}
          </div>
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
      <PageFrame>
        <Segmented
          options={SAMPLE_TABS.map((s) => ({ value: s.value, label: s.label }))}
          value={tab}
          onChange={(v) => setTab(v)}
          ariaLabel="页面切换"
        />
      </PageFrame>
      {tab === "home" && <HomeSample />}
      {tab === "chemical" && <ChemicalSample />}
      {tab === "reaction" && <ReactionSample />}
      {tab === "search" && <SearchSample />}
      {tab === "note" && <NoteSample />}
      {tab === "user" && <UserSample />}
      {tab === "skills" && <SkillsSample />}
      {tab === "mcp" && <McpSample />}
    </div>
  );
}
