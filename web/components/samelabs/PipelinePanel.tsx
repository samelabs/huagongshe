"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type ChainQueue = { queued: number; leased: number; error: number };
type Gate = { streak: number; silent: boolean; silent_remaining_s: number } | null;
type ChainBlock = {
  queue: ChainQueue;
  error_buckets: Record<string, number>;
  rate_1h: number;
  latest_at: string | null;
};
type LocaleRow = { locale: string; today: number; total: number; last_1h: number };
type LatestRow = { chain: string; chemical_id: number; source: string; ref: string; title: string; at: string | null };
type Pipeline = {
  cb: ChainBlock & {
    rows: { today: number; total: number };
    locales: LocaleRow[];
    seed: { accepted: number; enqueued: number; ambiguous: number };
    negative: { total: number; today: number };
  };
  pb: ChainBlock & { rows: { today: number; total: number } };
  gates: Record<string, Gate>;
  supplier: { today_rows: number; today_chemicals: number; total_rows: number; total_chemicals: number; profiles: number; today_profiles: number };
  latest: { cb: LatestRow[]; pb: LatestRow[] };
  workers: { worker_id: string; display_name: string | null; enabled: boolean; last_seen_at: string | null }[];
  generated_at: string;
};

const REFRESH_MS = 15000;
const LOCALE_NAME: Record<string, string> = { "zh-CN": "中文", en: "英文", de: "德文", ja: "日文", ko: "韩文" };
const OTHER_LOCALES = ["en", "de", "ja", "ko"];

const fmt = (n: number) => new Intl.NumberFormat("zh-CN").format(n);
const hm = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
const mins = (n: number) => (n >= 90 ? `${Math.round(n / 60)} 分` : `${n} 秒`);

function Dot({ ok }: { ok: boolean }) {
  return <span className={`pipe-dot ${ok ? "ok" : "bad"}`} aria-hidden />;
}

/* 指标格: 数量 + 今日新增 */
function Metric({ label, total, today }: { label: string; total: number; today?: number | null }) {
  return (
    <div className="pipe-metric">
      <span className="pipe-metric-label">{label}</span>
      <span className="pipe-metric-val">{fmt(total)}</span>
      {today !== undefined && today !== null && <span className="pipe-metric-label">今日 +{fmt(today)}</span>}
    </div>
  );
}

/* 单值行: 时间类指标 (最近入库) 不用数字格, 免得显示成 0 */
function MetaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="pipe-meta-line">
      <span className="pipe-metric-label">{label}</span>
      <span className="pipe-metric-val">{value}</span>
    </div>
  );
}

/* 指标组: 按数据源归类 (上游账本 / 队列 / 落库 / 供应侧) */
function Group({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="pipe-group">
      <div className="pipe-group-head">
        <span className="pipe-group-title">{title}</span>
        {note && <span className="pipe-group-note">{note}</span>}
      </div>
      <div className="pipe-metrics">{children}</div>
    </div>
  );
}

/* 单链最新 10 条: 链 / HCID / 来源 / 编号 / 标题(弹性列) / 时间 */
function LatestTable({ rows, chain }: { rows: LatestRow[]; chain: string }) {
  return (
    <div className="pipe-table" role="table">
      <div className="pipe-tr pipe-th pipe-tr-latest" role="row">
        <span>链</span><span>HCID</span><span>来源</span><span>编号</span><span>标题</span><span>时间</span>
      </div>
      {rows.length === 0
        ? <div className="pipe-tr pipe-tr-latest" role="row"><span className="pipe-empty">暂无数据</span></div>
        : rows.map((r) => (
          <div className="pipe-tr pipe-tr-latest" role="row" key={`${r.chemical_id}-${r.source}-${r.ref}`}>
            <span className={"pipe-locale" + (chain === "PB" ? " pb-tag" : "")}>{r.chain}</span>
            <span className="pipe-num">{fmt(r.chemical_id)}</span>
            <span className="pipe-src">{LOCALE_NAME[r.source] ?? r.source}</span>
            <span className="pipe-num" title={r.ref}>{r.ref}</span>
            <span className="pipe-detail" title={r.title}>{r.title}</span>
            <span className="pipe-num pipe-time">{hm(r.at)}</span>
          </div>
        ))}
    </div>
  );
}

/* error 行常显: 分桶 + 复活入口 (error=0 时按钮置灰但仍可见) */
function ErrorRow({ block, onRevive, reviving }: { block: ChainBlock; onRevive: () => void; reviving: boolean }) {
  const total = Object.values(block.error_buckets).reduce((a, b) => a + b, 0);
  return (
    <div className="pipe-error-row">
      <span className={total > 0 ? "pipe-err" : "pipe-ok"}>{total > 0 ? `error ${fmt(total)}` : "error 0"}</span>
      <span className="pipe-buckets">
        {Object.entries(block.error_buckets).slice(0, 4).map(([code, n]) => (
          <span key={code} className="pipe-chip error" title={code}>{code.replace(/^(pubchem|cpp|cas)_/, "")} {fmt(n)}</span>
        ))}
      </span>
      <button type="button" className="pipe-revive-btn" onClick={onRevive} disabled={reviving || total === 0}>
        {reviving ? "复活中…" : "复活全部"}
      </button>
    </div>
  );
}

export function SamelabsPipeline() {
  const [data, setData] = useState<Pipeline | null>(null);
  const [error, setError] = useState("");
  const [reviving, setReviving] = useState<"cb" | "pb" | null>(null);
  const aliveRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await apiGet<Pipeline>("/admin/pipeline");
      if (aliveRef.current) { setData(d); setError(""); }
    } catch (err) {
      if (!aliveRef.current) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => { aliveRef.current = false; window.clearInterval(id); };
  }, [load]);

  const revive = async (chain: "cb" | "pb") => {
    setReviving(chain);
    try {
      await apiPost(`/admin/pipeline/${chain}/errors/revive`);
      await load();
    } catch {
      setError(t.admin.errLoadFailed);
    } finally {
      setReviving(null);
    }
  };

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="context-loading">{t.common.loading}</p>;

  const sup = data.supplier;
  const loc = (code: string): LocaleRow | undefined => data.cb.locales.find((x) => x.locale === code);
  const zh = loc("zh-CN");
  const others = OTHER_LOCALES.map(loc).filter((x): x is LocaleRow => Boolean(x));
  const othersTotal = others.reduce((a, b) => a + b.total, 0);
  const othersToday = others.reduce((a, b) => a + b.today, 0);

  const cbActive = data.cb.queue.leased > 0 || data.cb.rate_1h > 0;
  const pbActive = data.pb.queue.leased > 0 || data.pb.rate_1h > 0;

  const gateChip = (gate: Gate) =>
    gate && gate.silent
      ? <span className="pipe-chip silent">静默中 · 剩 {mins(gate.silent_remaining_s)}</span>
      : gate && gate.streak > 0
        ? <span className="pipe-chip retry">连击 {gate.streak}</span>
        : null;

  const chainHead = (label: string, gate: Gate, active: boolean) => (
    <div className="pipe-chain-head">
      <span className="dashboard-card-label">{label}</span>
      {gateChip(gate)}
      <span className={"pipe-status-line" + (active ? "" : " idle")}>
        <Dot ok={active} /> {active ? "运行中" : "等待"}
      </span>
    </div>
  );

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.pipelineKicker}</p>
      <h1>{t.admin.pipelineTitle}</h1>
      <p>{t.admin.pipelineDesc(REFRESH_MS / 1000, hm(data.generated_at))}</p>
    </header>

    <section className="dashboard-section">
      <div className="dashboard-grid pipe-grid-2">

        {/* ── CB 链 · ChemicalBook 五语种 + 供应商 ── */}
        <div className="dashboard-card pipe-chain">
          {chainHead("CB 链 · ChemicalBook", data.gates.cb, cbActive)}

          <Group title="上游账本" note="chemicalbook_seed">
            <Metric label="待处理" total={data.cb.seed.accepted} />
            <Metric label="已入队" total={data.cb.seed.enqueued} />
            <Metric label="悬案" total={data.cb.seed.ambiguous} />
          </Group>

          <Group title="队列" note="cas_jobs">
            <Metric label="排队" total={data.cb.queue.queued} />
            <Metric label="在途" total={data.cb.queue.leased} />
            <Metric label="留痕" total={data.cb.queue.error} />
            <Metric label="近 1 小时" total={data.cb.rate_1h} />
          </Group>

          <Group title="落库" note="chemical_cb 五语种">
            <Metric label="中文" total={zh ? zh.total : 0} today={zh ? zh.today : 0} />
            <Metric label="其他语种合计" total={othersTotal} today={othersToday} />
            <Metric label="全链合计" total={data.cb.rows.total} today={data.cb.rows.today} />
          </Group>
          <MetaLine label="最近入库" value={hm(data.cb.latest_at)} />
          <div className="pipe-metrics pipe-sub">
            {others.map((l) => (
              <Metric key={l.locale} label={LOCALE_NAME[l.locale] ?? l.locale} total={l.total} today={l.today} />
            ))}
          </div>

          <Group title="供应侧" note="listing + profile">
            <Metric label="供应信息" total={sup.total_rows} today={sup.today_rows} />
            <Metric label="供应商" total={sup.profiles} today={sup.today_profiles} />
            <Metric label="今日覆盖化合物" total={sup.today_chemicals} />
            <Metric label="负面观测" total={data.cb.negative.total} today={data.cb.negative.today} />
          </Group>

          <ErrorRow block={data.cb} onRevive={() => revive("cb")} reviving={reviving === "cb"} />
        </div>

        {/* ── PB 链 · PubChem PUG View ── */}
        <div className="dashboard-card pipe-chain">
          {chainHead("PB 链 · PubChem PUG View", data.gates.pubchem, pbActive)}

          <Group title="队列" note="pubchem_jobs">
            <Metric label="排队" total={data.pb.queue.queued} />
            <Metric label="在途" total={data.pb.queue.leased} />
            <Metric label="留痕" total={data.pb.queue.error} />
            <Metric label="近 1 小时" total={data.pb.rate_1h} />
          </Group>

          <Group title="落库" note="chemical_pubchem">
            <Metric label="收录条目" total={data.pb.rows.total} today={data.pb.rows.today} />
          </Group>
          <MetaLine label="最近入库" value={hm(data.pb.latest_at)} />

          <ErrorRow block={data.pb} onRevive={() => revive("pb")} reviving={reviving === "pb"} />
        </div>
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>CB 链最新 10 条</h2><span>chemical_cb · 全语种</span></div>
      <LatestTable rows={data.latest.cb} chain="CB" />
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>PB 链最新 10 条</h2><span>chemical_pubchem</span></div>
      <LatestTable rows={data.latest.pb} chain="PB" />
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>Worker</h2><span>worker_clients</span></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th pipe-tr-4" role="row">
          <span>Worker</span><span>名称</span><span>状态</span><span>最近心跳</span>
        </div>
        {data.workers.length === 0
          ? <div className="pipe-tr pipe-tr-4" role="row"><span className="pipe-empty">暂无 worker</span></div>
          : data.workers.map((w) => (
            <div className="pipe-tr pipe-tr-4" role="row" key={w.worker_id}>
              <span className="pipe-locale">{w.worker_id}</span>
              <span>{w.display_name ?? "—"}</span>
              <span><Dot ok={w.enabled} /> {w.enabled ? "启用" : "停权"}</span>
              <span className="pipe-time">{hm(w.last_seen_at)}</span>
            </div>
          ))}
      </div>
    </section>
  </>;
}
