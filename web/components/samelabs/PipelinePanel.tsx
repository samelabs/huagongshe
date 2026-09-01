"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type ChainQueue = { queued: number; leased: number; error: number };
type ChainData = {
  queue: ChainQueue;
  error_buckets: Record<string, number>;
  latest: { chemical_id: number; at: string | null; locale?: string; status?: string }[];
};
type Pipeline = {
  cb: ChainData & {
    throughput_today: Record<string, number>;
    locales_today: { locale: string; status: string; count: number }[];
  };
  pb: ChainData & { throughput_today: number };
  gates: Record<string, { streak: number; silent: boolean; silent_remaining_s: number } | null>;
  workers: { worker_id: string; display_name: string | null; enabled: boolean; last_seen_at: string | null }[];
  generated_at: string;
};

const REFRESH_MS = 30000;
const LOCALE_ORDER = ["zh-CN", "en", "de", "ru", "ja", "ko"];

function fmt(n: number) { return new Intl.NumberFormat("zh-CN").format(n); }
function hm(iso: string | null) { return iso ? new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"; }

function QueueChip({ label, n }: { label: string; n: number }) {
  return <span className={"pipe-chip" + (n > 0 ? " " + label : "")}>{label} {fmt(n)}</span>;
}

function GateBadge({ g }: { g: { streak: number; silent: boolean; silent_remaining_s: number } | null }) {
  if (!g) return <span className="muted">闸门 n/a</span>;
  if (g.silent) return <span className="pipe-alert">静默中 · 剩余 {Math.ceil(g.silent_remaining_s / 60)} 分</span>;
  return <span className={"pipe-chip" + (g.streak > 0 ? " error" : "")}>连击 {g.streak}</span>;
}

function ErrorBuckets({ buckets, onRevive, reviving }: {
  buckets: Record<string, number>; onRevive: () => void; reviving: boolean;
}) {
  const entries = Object.entries(buckets);
  const total = entries.reduce((a, [, n]) => a + n, 0);
  if (total === 0) return <span className="pipe-chips"><span className="pipe-chip">error 0</span></span>;
  return (
    <span className="pipe-chips">
      {entries.map(([code, n]) => (
        <span key={code} className="pipe-chip error" title={code}>{code} {fmt(n)}</span>
      ))}
      <button className="pipe-revive-btn" onClick={onRevive} disabled={reviving}>
        {reviving ? "复活中…" : `一键复活 ${fmt(total)}`}
      </button>
    </span>
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
    try {
      await apiPost(`/admin/pipeline/${chain}/errors/revive`);
      load();
    } catch { setError(t.admin.errLoadFailed); }
    setReviving(null);
  };

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="context-loading">{t.common.loading}</p>;

  const byLocale = new Map<string, Record<string, number>>();
  for (const row of data.cb.locales_today) {
    const cur = byLocale.get(row.locale) ?? {};
    cur[row.status] = (cur[row.status] ?? 0) + row.count;
    byLocale.set(row.locale, cur);
  }
  const localeRows = LOCALE_ORDER.filter((l) => byLocale.has(l)).map((l) => {
    const m = byLocale.get(l) ?? {};
    return { locale: l, ok: m["ok"] ?? 0, not_found: m["not_found"] ?? 0 };
  });
  const cbTotal = data.cb.queue.queued + data.cb.queue.leased + data.cb.queue.error;
  const pbTotal = data.pb.queue.queued + data.pb.queue.leased + data.pb.queue.error;

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.pipelineKicker}</p>
      <h1>{t.admin.pipelineTitle}</h1>
      <p className="page-desc">{t.admin.pipelineDesc(REFRESH_MS / 1000, hm(data.generated_at))}</p>
    </header>

    <section className="dashboard-section">
      <div className="section-heading"><h2>CB 链 · ChemicalBook</h2><GateBadge g={data.gates.cb} /></div>
      <div className="dashboard-grid">
        <div className="dashboard-card">
          <span className="dashboard-card-label">队列</span>
          <strong className="dashboard-card-value">{fmt(cbTotal)}</strong>
          <span className="pipe-chips">
            <QueueChip label="queued" n={data.cb.queue.queued} />
            <QueueChip label="leased" n={data.cb.queue.leased} />
            <QueueChip label="error" n={data.cb.queue.error} />
          </span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">今日落库</span>
          <strong className="dashboard-card-value">{fmt(data.cb.throughput_today.ok ?? 0)}</strong>
          <span className="dashboard-card-sub">ok · not_found {fmt(data.cb.throughput_today.not_found ?? 0)}</span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">error 分桶</span>
          <div className="dashboard-card-sub">
            <ErrorBuckets buckets={data.cb.error_buckets} onRevive={() => revive("cb")} reviving={reviving === "cb"} />
          </div>
        </div>
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>PB 链 · PubChem</h2><GateBadge g={data.gates.pubchem} /></div>
      <div className="dashboard-grid">
        <div className="dashboard-card">
          <span className="dashboard-card-label">队列</span>
          <strong className="dashboard-card-value">{fmt(pbTotal)}</strong>
          <span className="pipe-chips">
            <QueueChip label="queued" n={data.pb.queue.queued} />
            <QueueChip label="leased" n={data.pb.queue.leased} />
            <QueueChip label="error" n={data.pb.queue.error} />
          </span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">今日落库</span>
          <strong className="dashboard-card-value">{fmt(data.pb.throughput_today)}</strong>
          <span className="dashboard-card-sub">chemical_pubchem 行</span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">error 分桶</span>
          <div className="dashboard-card-sub">
            <ErrorBuckets buckets={data.pb.error_buckets} onRevive={() => revive("pb")} reviving={reviving === "pb"} />
          </div>
        </div>
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>Worker</h2></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th" role="row">
          <span>ID</span><span>名称</span><span>状态</span><span>最近活跃</span>
        </div>
        {data.workers.map((w) => (
          <div className="pipe-tr" role="row" key={w.worker_id}>
            <span className="pipe-locale">{w.worker_id}</span>
            <span>{w.display_name ?? "—"}</span>
            <span className={w.enabled ? "" : "pipe-err"}>{w.enabled ? "启用" : "停权"}</span>
            <span className="muted">{hm(w.last_seen_at)}</span>
          </div>
        ))}
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>CB 今日分语言</h2></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th" role="row">
          <span>{t.admin.pipeLocale}</span><span>ok</span><span>not_found</span><span>{t.admin.pipeLastAt}</span>
        </div>
        {localeRows.map((r) => (
          <div className="pipe-tr" role="row" key={r.locale}>
            <span className="pipe-locale">{r.locale}</span>
            <span>{fmt(r.ok ?? 0)}</span>
            <span className="muted">{fmt(r.not_found ?? 0)}</span>
            <span className="muted" />
          </div>
        ))}
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>最新落库</h2></div>
      <div className="pipe-table" role="table">
        {data.cb.latest.map((r, i) => (
          <div className="pipe-tr" role="row" key={"cb" + i}>
            <span className="pipe-locale">CB · {r.locale ?? "zh-CN"}</span>
            <span>HCID {r.chemical_id}</span>
            <span className={r.status === "error" ? "pipe-err" : "muted"}>{r.status}</span>
            <span className="muted">{hm(r.at)}</span>
          </div>
        ))}
        {data.pb.latest.map((r, i) => (
          <div className="pipe-tr" role="row" key={"pb" + i}>
            <span className="pipe-locale">PB</span>
            <span>HCID {r.chemical_id}</span>
            <span className="muted" />
            <span className="muted">{hm(r.at)}</span>
          </div>
        ))}
      </div>
    </section>
  </>;
}
