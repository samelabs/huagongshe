"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type ChainQueue = { queued: number; leased: number; error: number };
type Gate = { streak: number; silent: boolean; silent_remaining_s: number } | null;
type ChainBlock = {
  queue: ChainQueue;
  error_buckets: Record<string, number>;
  throughput: { ok: number; not_found: number; total: number };
  rate_1h: number;
  latest_at: string | null;
};
type Pipeline = {
  cb: ChainBlock & { locales_today: { locale: string; ok: number; not_found: number }[] };
  pb: ChainBlock;
  gates: Record<string, Gate>;
  supplier: { today_rows: number; today_chemicals: number; total_rows: number; total_chemicals: number; profiles: number };
  latest: { chain: string; chemical_id: number; detail: string; status: string; at: string | null }[];
  workers: { worker_id: string; display_name: string | null; enabled: boolean; last_seen_at: string | null }[];
  generated_at: string;
};

const REFRESH_MS = 15000;
const LOCALES = ["zh-CN", "en", "de", "ru", "ja", "ko"];
const LOCALE_NAME: Record<string, string> = { "zh-CN": "中文", en: "英文", de: "德文", ru: "俄文", ja: "日文", ko: "韩文" };

const fmt = (n: number) => new Intl.NumberFormat("zh-CN").format(n);
const hm = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
const mins = (n: number) => (n >= 90 ? `${Math.round(n / 60)} 分` : `${n} 秒`);

function Dot({ ok }: { ok: boolean }) {
  return <span className={`pipe-dot ${ok ? "ok" : "bad"}`} aria-hidden />;
}

function ChainCard({ name, source, data, gate, supplier, onRevive, reviving }: {
  name: string; source: string; data: ChainBlock; gate: Gate;
  supplier?: { today_rows: number; today_chemicals: number; total_rows: number; total_chemicals: number; profiles: number };
  onRevive: () => void; reviving: boolean;
}) {
  const active = data.queue.leased > 0 || data.rate_1h > 0;
  const errorTotal = Object.values(data.error_buckets).reduce((a, b) => a + b, 0);
  return (
    <div className="dashboard-card pipe-chain">
      <div className="pipe-chain-head">
        <span className="dashboard-card-label">{source}</span>
        {gate && gate.silent
          ? <span className="pipe-chip silent">静默中 · 剩 {mins(gate.silent_remaining_s)}</span>
          : gate && gate.streak > 0
            ? <span className="pipe-chip retry">连击 {gate.streak}</span>
            : null}
      </div>
      <strong className="dashboard-card-value">{fmt(data.throughput.total)}</strong>
      <span className="dashboard-card-sub">
        今日入库 {fmt(data.throughput.total)} · 近1小时 {fmt(data.rate_1h)} /时
      </span>
      <div className="pipe-metrics">
        <div className="pipe-metric">
          <span className="pipe-metric-label">队列</span>
          <span className="pipe-metric-val">{fmt(data.queue.queued)}</span>
          <span className="pipe-metric-label">在途 {fmt(data.queue.leased)} · 留痕 {fmt(data.queue.error)}</span>
        </div>
        <div className="pipe-metric">
          <span className="pipe-metric-label">{data.throughput.not_found >= 0 ? "判定分布" : "数据源"}</span>
          <span className="pipe-metric-val">{data.throughput.not_found >= 0
            ? `${fmt(data.throughput.ok)} 有 / ${fmt(data.throughput.not_found)} 无`
            : "PUG View 整包"}</span>
          <span className="pipe-metric-label">最近入库 {hm(data.latest_at)}</span>
        </div>
        {supplier && (
          <div className="pipe-metric">
            <span className="pipe-metric-label">供应商报价</span>
            <span className="pipe-metric-val">今日 {fmt(supplier.today_rows)}</span>
            <span className="pipe-metric-label">今日覆盖 {fmt(supplier.today_chemicals)} 化合物</span>
            <span className="pipe-metric-label">listing 总 {fmt(supplier.total_rows)} 条 · {fmt(supplier.total_chemicals)} 化合物 · 厂商档案 {fmt(supplier.profiles)}</span>
          </div>
        )}
      </div>
      {errorTotal > 0 && (
        <div className="pipe-error-row">
          <span className="pipe-err">error {fmt(errorTotal)}</span>
          <span className="pipe-buckets">
            {Object.entries(data.error_buckets).slice(0, 4).map(([code, n]) => (
              <span key={code} className="pipe-chip error" title={code}>{code.replace(/^(pubchem|cpp|cas)_/, "")} {fmt(n)}</span>
            ))}
          </span>
          <button className="pipe-revive-btn" onClick={onRevive} disabled={reviving}>
            {reviving ? "复活中…" : "复活全部"}
          </button>
        </div>
      )}
      <span className={"pipe-status-line " + (active ? "" : "idle")}>
        <Dot ok={active} /> {active ? "运行中" : "等待"}
      </span>
    </div>
  );
}

export function SamelabsPipeline() {
  const [data, setData] = useState<Pipeline | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [reviving, setReviving] = useState<string | null>(null);

  const load = () => {
    apiGet<Pipeline>(`/admin/pipeline`).then((d) => { setData(d); setError(""); })
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
        else setError(t.admin.errLoadFailed);
      });
  };

  useEffect(() => { load(); }, [tick]);
  useEffect(() => {
    const id = window.setInterval(() => setTick((x) => x + 1), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  const revive = async (chain: "cb" | "pb") => {
    setReviving(chain);
    try { await apiPost(`/admin/pipeline/${chain}/errors/revive`); load(); }
    catch { setError(t.admin.errLoadFailed); }
    setReviving(null);
  };

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="context-loading">{t.common.loading}</p>;

  const liveWorkers = data.workers.filter((w) => w.enabled);

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.pipelineKicker}</p>
      <h1>{t.admin.pipelineTitle}</h1>
      <p className="page-desc">{t.admin.pipelineDesc(REFRESH_MS / 1000, hm(data.generated_at))}</p>
    </header>

    <section className="dashboard-section">
      <div className="dashboard-grid pipe-grid-2">
        <ChainCard name="CB" source="CB 链 · ChemicalBook" data={data.cb} gate={data.gates.cb}
          supplier={data.supplier}
          onRevive={() => revive("cb")} reviving={reviving === "cb"} />
        <ChainCard name="PB" source="PB 链 · PubChem" data={data.pb} gate={data.gates.pubchem}
          onRevive={() => revive("pb")} reviving={reviving === "pb"} />
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>Worker</h2></div>
      <div className="pipe-table" role="table">
        {liveWorkers.map((w) => (
          <div className="pipe-tr pipe-tr-4" role="row" key={w.worker_id}>
            <span className="pipe-locale">{w.worker_id}</span>
            <span>{w.display_name ?? "—"}</span>
            <span><Dot ok={w.enabled} /> {w.enabled ? "启用" : "停权"}</span>
            <span className="muted">{hm(w.last_seen_at)}</span>
          </div>
        ))}
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>实时入库</h2>
        <span className="muted">两链最新 10 条</span>
      </div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th pipe-tr-latest" role="row">
          <span>链</span><span>HCID</span><span>内容</span><span>判定</span><span>时间</span>
        </div>
        {data.latest.map((r, i) => (
          <div className="pipe-tr pipe-tr-latest" role="row" key={i}>
            <span className={"pipe-locale " + (r.chain === "PB" ? "pb-tag" : "")}>{r.chain}</span>
            <span>{fmt(r.chemical_id)}</span>
            <span className="pipe-detail" title={r.detail}>{r.detail || "—"}</span>
            <span className={r.status === "ok" ? "" : "muted"}>{r.status === "ok" ? "有数据" : "无收录"}</span>
            <span className="muted">{hm(r.at)}</span>
          </div>
        ))}
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>CB 今日分语言</h2></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th pipe-tr-4" role="row">
          <span>语言</span><span>有数据</span><span>无收录</span><span>合计</span>
        </div>
        {LOCALES.filter((l) => data.cb.locales_today.some((x) => x.locale === l)).map((l) => {
          const row = data.cb.locales_today.find((x) => x.locale === l)!;
          return (
            <div className="pipe-tr pipe-tr-4" role="row" key={l}>
              <span className="pipe-locale">{LOCALE_NAME[l] ?? l}</span>
              <span>{fmt(row.ok)}</span>
              <span className="muted">{fmt(row.not_found)}</span>
              <span className="muted">{fmt(row.ok + row.not_found)}</span>
            </div>
          );
        })}
      </div>
    </section>
  </>;
}
