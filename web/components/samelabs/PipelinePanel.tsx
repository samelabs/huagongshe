"use client";

import { useEffect, useState } from "react";
import { apiGet, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type Pipeline = {
  queues: {
    cas: Record<string, number>;
    pb: Record<string, number>;
    zombie_leases: { cas: number; pb: number };
  };
  today: {
    cas: Record<string, number>;
    pb: Record<string, number>;
    locales: { locale: string; status: string; count: number; last_at: string | null }[];
  };
  listing: {
    today_rows: number; today_chemicals: number; last_hour_rows: number;
    total_rows: number; total_chemicals: number; profiles: number;
  };
  latest: { chemical_id: number; locale: string; status: string; at: string | null }[];
  generated_at: string;
};

const REFRESH_MS = 30000;
const LOCALE_ORDER = ["zh-CN", "en", "de", "ru", "ja", "ko"];

function fmt(n: number) { return new Intl.NumberFormat("zh-CN").format(n); }
function hm(iso: string | null) { return iso ? new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"; }

function QueueChip({ label, n }: { label: string; n: number }) {
  return <span className={"pipe-chip" + (n > 0 ? " " + label : "")}>{label} {fmt(n)}</span>;
}

export function SamelabsPipeline() {
  const [data, setData] = useState<Pipeline | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    apiGet<Pipeline>(`/admin/pipeline`).then((d) => { if (active) { setData(d); setError(""); } })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
        else setError(t.admin.errLoadFailed);
      });
    return () => { active = false; };
  }, [tick]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((x) => x + 1), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="context-loading">{t.common.loading}</p>;

  const casZombie = data.queues.zombie_leases.cas + data.queues.zombie_leases.pb;
  const byLocale = new Map<string, { ok: number; not_found: number; error: number; last: string | null }>();
  for (const row of data.today.locales) {
    const cur = byLocale.get(row.locale) ?? { ok: 0, not_found: 0, error: 0, last: null };
    if (row.status in cur) (cur as any)[row.status] += row.count;
    if (!cur.last || (row.last_at && row.last_at > cur.last)) cur.last = row.last_at;
    byLocale.set(row.locale, cur);
  }
  const localeRows = LOCALE_ORDER.filter((l) => byLocale.has(l)).map((l) => ({ locale: l, ...byLocale.get(l)! }));

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.pipelineKicker}</p>
      <h1>{t.admin.pipelineTitle}</h1>
      <p className="page-desc">{t.admin.pipelineDesc(REFRESH_MS / 1000, hm(data.generated_at))}</p>
    </header>

    <section className="dashboard-section">
      <div className="section-heading"><h2>{t.admin.pipeQueues}</h2>
        {casZombie > 0 && <span className="pipe-alert">{t.admin.pipeZombie(casZombie)}</span>}
      </div>
      <div className="dashboard-grid">
        <div className="dashboard-card">
          <span className="dashboard-card-label">CAS</span>
          <strong className="dashboard-card-value">{fmt(Object.values(data.queues.cas).reduce((a, b) => a + b, 0))}</strong>
          <span className="pipe-chips">
            <QueueChip label="queued" n={data.queues.cas.queued ?? 0} />
            <QueueChip label="retry" n={data.queues.cas.retry ?? 0} />
            <QueueChip label="leased" n={data.queues.cas.leased ?? 0} />
            <QueueChip label="dead" n={data.queues.cas.dead ?? 0} />
          </span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">PubChem</span>
          <strong className="dashboard-card-value">{fmt(Object.values(data.queues.pb).reduce((a, b) => a + b, 0))}</strong>
          <span className="pipe-chips">
            <QueueChip label="queued" n={data.queues.pb.queued ?? 0} />
            <QueueChip label="retry" n={data.queues.pb.retry ?? 0} />
            <QueueChip label="leased" n={data.queues.pb.leased ?? 0} />
            <QueueChip label="dead" n={data.queues.pb.dead ?? 0} />
          </span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">{t.admin.pipeToday}</span>
          <strong className="dashboard-card-value">{fmt((data.today.cas.succeeded ?? 0) + (data.today.pb.succeeded ?? 0))}</strong>
          <span className="dashboard-card-sub">CAS {fmt(data.today.cas.succeeded ?? 0)} · PB {fmt(data.today.pb.succeeded ?? 0)}</span>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">{t.admin.pipeListingToday}</span>
          <strong className="dashboard-card-value">{fmt(data.listing.today_rows)}</strong>
          <span className="dashboard-card-sub">{t.admin.pipeListingSub(fmt(data.listing.today_chemicals), fmt(data.listing.last_hour_rows))}</span>
        </div>
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>{t.admin.pipeLocales}</h2></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th" role="row">
          <span>{t.admin.pipeLocale}</span><span>ok</span><span>not_found</span><span>error</span><span>{t.admin.pipeLastAt}</span>
        </div>
        {localeRows.map((r) => (
          <div className="pipe-tr" role="row" key={r.locale}>
            <span className="pipe-locale">{r.locale}</span>
            <span>{fmt(r.ok)}</span>
            <span className="muted">{fmt(r.not_found)}</span>
            <span className={r.error > 0 ? "pipe-err" : "muted"}>{fmt(r.error)}</span>
            <span className="muted">{hm(r.last)}</span>
          </div>
        ))}
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>{t.admin.pipeLatest}</h2>
        <span className="muted">{t.admin.pipeTotals(fmt(data.listing.total_rows), fmt(data.listing.total_chemicals), fmt(data.listing.profiles))}</span>
      </div>
      <div className="pipe-table" role="table">
        {data.latest.map((r, i) => (
          <div className="pipe-tr" role="row" key={i}>
            <span className="pipe-locale">{r.locale ?? "主行"}</span>
            <span>HCID {r.chemical_id}</span>
            <span className={r.status === "error" ? "pipe-err" : "muted"}>{r.status}</span>
            <span className="muted">{hm(r.at)}</span>
          </div>
        ))}
      </div>
    </section>
  </>;
}
