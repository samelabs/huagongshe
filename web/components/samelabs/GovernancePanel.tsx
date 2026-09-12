"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

/* ── A2 治理契约 ──────────────────────────────────────────
   三层语义: source_record / canonical_entity / derived_index — 界面文案钉死。
   每指标: {available, value, error, mode(exact|sample|estimate|deferred)}。
   unavailable ≠ 0。drill-down LIMIT 50。只读, 无修复按钮。 */

type Gov = {
  sections: Record<string, { available: boolean; value: any; error: string | null; mode: string }>;
  generated_at: string;
  stale: boolean;
  ttl_seconds: number;
};
type Drill = { available: boolean; error: string | null; columns: string[]; rows: any[][]; limit: number };

const hm = (iso: string | null) => (iso ? new Date(isecondsSafe(iso)).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
function isecondsSafe(iso: string) { return iso; }
const fmt = (n: number) => new Intl.NumberFormat("zh-CN").format(n);

function Block({ label, value, note, layer, onDrill }: { label: string; value: string; note?: string; layer?: "source_record" | "canonical_entity" | "derived_index"; onDrill?: () => void }) {
  return (
    <div className="gov-cell">
      <span className="pipe-metric-label">
        {label}
        {layer && <span className="gov-layer" title={layer}>{LAYER_LABEL[layer]}</span>}
      </span>
      <span className={"pipe-metric-val" + (onDrill ? " gov-drillable" : "")} onClick={onDrill}>{value}</span>
      {note && <span className="pipe-metric-label">{note}</span>}
    </div>
  );
}

const LAYER_LABEL: Record<string, string> = {
  source_record: "源记录",
  canonical_entity: "主档",
  derived_index: "派生索引",
};

function Section({ title, note, children, unavailable }: { title: string; note?: string; children: React.ReactNode; unavailable?: string | null }) {
  return (
    <div className="dashboard-card gov-section">
      <div className="pipe-group-head">
        <span className="pipe-group-title">{title}</span>
        {note && <span className="pipe-group-note">{note}</span>}
      </div>
      <div className="pipe-metrics">{children}</div>
      {unavailable && <div className="pipe-section-unavailable">{t.admin.sectionUnavailable}{unavailable ? `（${unavailable}）` : ""}</div>}
    </div>
  );
}

export function SamelabsGovernance() {
  const [gov, setGov] = useState<Gov | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "stale" | "error">("loading");
  const [err, setErr] = useState("");
  const [drill, setDrill] = useState<{ key: string; data: Drill | null } | null>(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const g = await apiGet<Gov>("/admin/pipeline/governance");
      if (!alive.current) return;
      setGov(g); setPhase("ready"); setErr("");
    } catch (e) {
      if (!alive.current) return;
      if (govRef.current === null) { setErr(e instanceof ApiError ? String(e.status) : "load failed"); setPhase("error"); }
      else setPhase("stale");
    }
  }, []);
  const govRef = useRef<Gov | null>(null); govRef.current = gov;

  useEffect(() => { alive.current = true; load(); return () => { alive.current = false; }; }, [load]);

  const openDrill = async (key: string) => {
    setDrill({ key, data: null });
    try {
      const d = await apiGet<Drill>(`/admin/pipeline/governance/drilldown/${key}`);
      setDrill({ key, data: d });
    } catch {
      setDrill({ key, data: { available: false, error: "请求失败", columns: [], rows: [], limit: 50 } });
    }
  };

  if (phase === "error") return <div className="notice error">{t.admin.govLoadFailed}
    <button type="button" className="pipe-retry-btn" onClick={() => { setErr(""); setPhase("loading"); load(); }}>{t.admin.retryNow}</button></div>;
  if (!gov) return <p className="context-loading">{t.common.loading}</p>;

  const S = gov.sections;
  const w = (k: string) => S[k] ?? { available: false, value: null, error: "missing", mode: "error" };
  const v = (k: string) => (w(k).available ? w(k).value : null);
  const un = (k: string) => (w(k).available ? null : (w(k).error ?? "unknown"));
  const mode = (k: string) => w(k).mode;
  const modeNote = (k: string) => mode(k) === "sample" ? "样本口径" : mode(k) === "deferred" ? "暂缓" : mode(k) === "estimate" ? "估算" : "";

  const nim = v("cb_name_index_missing");
  const cbnull = v("cb_canonical_cb_number_null");
  const locg = v("cb_locale_gaps");
  const supor = v("supplier_listing_orphan");
  const seednj = w("seed_enqueued_no_job");
  const pbgap = v("pb_canonical_sync_gap");
  const pbnorec = v("pb_cid_no_source_record");
  const nior = v("name_index_orphan");
  const nidist = v("name_index_distribution");
  const cov = v("canonical_name_coverage");
  const idg = v("identity_governance");

  // 抽样指标统一文案: "样本 matched/size (ratio)" — 禁写成全库异常总数
  const sv = (x: any) => (x ? `${fmt(x.matched)}/${fmt(x.sample_size)}（${((x.ratio ?? 0) * 100).toFixed(1)}%）` : null);
  const issues: { key: string; sev: string; label: string; val: string | null; drill?: string; modeK?: string }[] = [
    { key: "ambiguous", sev: "高", label: "CB 采集/身份悬案 (seed AMBIGUOUS)", val: idg ? fmt(idg.acquisition_pending.ambiguous_seeds) : null, drill: "identity_ambiguous_seeds", modeK: "identity_governance" },
    { key: "ni_missing", sev: "高", label: "CB 中文名未镜像 name_index（样本）", val: sv(nim), drill: "cb_name_index_missing", modeK: "cb_name_index_missing" },
    { key: "sup_orphan", sev: "高", label: "Supplier listing 指向不存在主档（样本）", val: supor ? `${fmt(supor.matched)}/${fmt(supor.sample_size)}` : null, drill: "supplier_listing_orphan", modeK: "supplier_listing_orphan" },
    { key: "ni_orphan", sev: "中", label: "name_index 指向不存在主档（样本）", val: nior ? `${fmt(nior.matched)}/${fmt(nior.sample_size)}` : null, drill: "name_index_orphan", modeK: "name_index_orphan" },
    { key: "cb_num_null", sev: "中", label: "源记录有但主档 cb_number 空（样本）", val: sv(cbnull), drill: "cb_canonical_cb_number_null", modeK: "cb_canonical_cb_number_null" },
    { key: "pb_norec", sev: "中", label: "主档有 CID 但无 PB 源记录（样本）", val: sv(pbnorec), drill: "pb_cid_no_source_record", modeK: "pb_cid_no_source_record" },
    { key: "pb_gap", sev: "中", label: "PB 源记录未同步主档字段（样本）", val: sv(pbgap), modeK: "pb_canonical_sync_gap" },
    { key: "seed_nj", sev: "低", label: "Seed ENQUEUED 但无活跃 job", val: seednj.available ? fmt(seednj.value ?? 0) : null, modeK: "seed_enqueued_no_job" },
  ];

  return <>
    <header className="page-title">
      <p className="page-kicker">GOVERNANCE</p>
      <h1>{t.admin.govTitle}</h1>
      <p>{t.admin.govDesc}</p>
      <div className="pipe-snapshot-line">
        <span>快照 {hm(gov.generated_at)}{gov.stale ? ` · ${t.admin.statsStale}` : ""} · TTL {gov.ttl_seconds}s · 只读诊断</span>
      </div>
    </header>

    {phase === "stale" && <div className="notice warn pipe-stale-banner">{t.admin.refreshFailed(hm(gov.generated_at))}
      <button type="button" className="pipe-retry-btn" onClick={() => { setPhase("loading"); load(); }}>{t.admin.retryNow}</button></div>}

    {/* Identity governance */}
    <section className="dashboard-section">
      <div className="section-heading"><h2>Identity Governance</h2><span>merge / redirect / 账本终态 —— 真实持久化维度</span></div>
      <div className="dashboard-grid pipe-grid-2">
        <Section title="上游账本终态" note="chemicalbook_seed">
          {idg ? Object.entries(idg.seed_ledger).map(([k, n]) => (
            <Block key={k} label={k} value={fmt(n as number)} layer="source_record"
              onDrill={k === "AMBIGUOUS" ? () => openDrill("identity_ambiguous_seeds") : k === "CONFLICT" ? () => openDrill("identity_conflict_seeds") : undefined} />
          )) : <Block label="账本" value="暂不可用" />}
        </Section>
        <Section title="历史治理记录" note="已执行 merge 留痕">
          {idg?.history ? <>
            <Block label="历史合并" value={fmt(idg.history.merge_total)} onDrill={() => openDrill("identity_merge_log")} layer="canonical_entity" />
            <Block label="近 24h 合并" value={fmt(idg.history.merged_last_24h)} />
            <Block label="重定向行" value={fmt(idg.history.redirect_total)} layer="canonical_entity" />
          </> : <Block label="历史治理记录" value="暂不可用" />}
        </Section>
        <Section title="Resolver 事件" note="逐次 AMBIGUOUS/CONFLICT 判定">
          <div className="gov-gap-note">当前无可统计的 resolver 持久化事件（不以上游账本或 merge 记录顶替）</div>
        </Section>
      </div>
    </section>

    {/* Governance Issues */}
    <section className="dashboard-section">
      <div className="section-heading"><h2>Governance Issues</h2><span>按严重度 · 点击可展开样本（≤50）</span></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th pipe-tr-gov" role="row"><span>级别</span><span>问题</span><span>数值</span><span>口径</span><span></span></div>
        {issues.map(i => (
          <div className="pipe-tr pipe-tr-gov" role="row" key={i.key}>
            <span className={"gov-sev " + (i.sev === "高" ? "bad" : "warn")}>{i.sev}</span>
            <span className="pipe-detail">{i.label}</span>
            <span className="pipe-num">{i.val ?? "暂不可用"}</span>
            <span className="pipe-metric-label">{modeNote(i.modeK ?? i.key)}</span>
            <span>{i.drill && i.val && i.val !== "0" && i.val !== "0/0"
              ? <button type="button" className="pipe-retry-btn" onClick={() => openDrill(i.drill!)}>样本</button>
              : <span className="pipe-metric-label">{i.val === "0" ? "真 0" : ""}</span>}</span>
          </div>
        ))}
      </div>
    </section>

    {/* Coverage / Search readiness */}
    <section className="dashboard-section">
      <div className="section-heading"><h2>Coverage · Search Readiness</h2><span>只审计展示, 不改 Search</span></div>
      <div className="dashboard-grid pipe-grid-2">
        <Section title="主档命名覆盖" note="canonical chemicals · 样本比率">
          {cov ? <>
            <Block label="主档总量(估)" value={fmt(cov.chemicals_estimated)} layer="canonical_entity" />
            <Block label="preferred_name" value={`${(cov.preferred_name_rate * 100).toFixed(1)}%`} note={`样本 ${fmt(cov.sample_rows)}`} layer="canonical_entity" />
            <Block label="iupac_name" value={`${(cov.iupac_name_rate * 100).toFixed(1)}%`} layer="canonical_entity" />
            <Block label="molecular_formula" value={`${(cov.formula_rate * 100).toFixed(1)}%`} layer="canonical_entity" />
            <Block label="pubchem_cid" value={`${(cov.pubchem_cid_rate * 100).toFixed(1)}%`} layer="canonical_entity" />
          </> : <Block label="覆盖" value="暂不可用" />}
        </Section>
        <Section title="派生索引 name_index" note="derived_index · kind/lang/source">
          {nidist ? nidist.slice(0, 8).map((d: any) => (
            <Block key={`${d.kind}-${d.lang}-${d.source}`} label={`${d.kind}·${d.lang}·${d.source}`} value={fmt(d.count)} layer="derived_index" note={d.kind === "supplier" ? "供应商货名, 非展示名" : undefined} />
          )) : <Block label="分布" value="暂不可用" />}
        </Section>
      </div>
    </section>

    {/* drill-down dialog */}
    {drill && (
      <div className="pipe-confirm" role="dialog" aria-modal onClick={() => setDrill(null)}>
        <div className="pipe-confirm-box gov-drill-box" onClick={e => e.stopPropagation()}>
          <div className="pipe-group-head"><span className="pipe-group-title">样本 · {drill.key}</span>
            <button type="button" className="pipe-retry-btn" onClick={() => setDrill(null)}>关闭</button></div>
          {!drill.data && <p className="context-loading">{t.common.loading}</p>}
          {drill.data && (!drill.data.available
            ? <p className="notice error">{drill.data.error || "当前没有持久化证据，无法 drill-down"}</p>
            : <div className="pipe-table gov-drill-table">
              <div className="pipe-tr pipe-th" role="row">{drill.data.columns.map(c => <span key={c}>{c}</span>)}</div>
              {drill.data.rows.length === 0 && <div className="pipe-tr" role="row"><span>无异常样本（真 0）</span></div>}
              {drill.data.rows.map((r, i) => (
                <div className="pipe-tr" role="row" key={i}>{r.map((c, j) => <span key={j} className={typeof c === "number" ? "pipe-num" : ""}>{c === null ? "—" : typeof c === "number" ? fmt(c) : String(c)}</span>)}</div>
              ))}
              <div className="pipe-metric-label">上限 {drill.data.limit} 条</div>
            </div>)}
        </div>
      </div>
    )}
  </>;
}
