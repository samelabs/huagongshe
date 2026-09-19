"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

/* ── A1 数据契约 ──────────────────────────────────────────
   optional sections 形状: seed/negative(来源未命中)属 CB 上游账本, supplier 属供应侧:
   { available: boolean; error: string | null; value: T | null }
   available=false → 渲染"暂不可用", 绝不把 0 冒充数据。 */

type ChainQueue = { queued: number; leased: number; error: number };
type Aging = { oldest_queued_age_s: number | null };
type Health = { status: string; has_recent_worker: boolean; recent_success: boolean; reasons: string[] };
type Gate = { streak: number; silent: boolean; silent_remaining_s: number } | null;
type ChainBlock = {
  queue: ChainQueue;
  error_buckets: Record<string, number>;
  rate_1h: number;
  latest_at: string | null;
  aging: Aging;
  health: Health;
};
type Optional<T> = { available: boolean; error: string | null; value: T | null };
type LocaleRow = { locale: string; today: number; total: number; last_1h: number };
type LatestRow = { chain: string; chemical_id: number; source: string; ref: string; title: string; at: string | null };
type Pipeline = {
  cb: ChainBlock & {
    rows: { today: number; total: number };
    locales: LocaleRow[];
    seed: Optional<{ accepted: number; enqueued: number; ambiguous: number }>;
    negative: Optional<{ total: number; today: number }>;
  };
  pb: ChainBlock & { rows: { today: number; total: number } };
  gates: Record<string, Gate>;
  gates_meta: { available: boolean; error: string | null };
  supplier: Optional<{ today_rows: number; total_rows: number; profiles: number; today_profiles: number }>;
  latest: { cb: LatestRow[]; pb: LatestRow[] };
  workers: { worker_id: string; display_name: string | null; enabled: boolean; scopes: string[]; runtime: string; last_seen_at: string | null; last_seen_age_s: number | null }[];
  stats: { generated_at: string; stale: boolean; age_seconds: number; ttl_seconds: number };
  generated_at: string;
};

/* ── 加载状态机: initial_loading / ready / refreshing / stale ── */
type LoadPhase = "initial_loading" | "ready" | "refreshing" | "stale";

const REFRESH_MS = 15000;
const LOCALE_NAME: Record<string, string> = { "zh-CN": "中文", en: "英文", de: "德文", ja: "日文", ko: "韩文" };
const OTHER_LOCALES = ["en", "de", "ja", "ko"];
const SCOPE_LABEL: Record<string, string> = { pubchem: "PubChem", cas: "ChemicalBook" };

const fmt = (n: number) => new Intl.NumberFormat("zh-CN").format(n);
const hm = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
const mins = (n: number) => (n >= 90 ? `${Math.round(n / 60)} 分` : `${n} 秒`);
const dur = (s: number | null) => {
  if (s == null) return "—";
  if (s < 90) return `${s} 秒`;
  if (s < 5400) return `${Math.round(s / 60)} 分`;
  return `${Math.round(s / 3600)} 时`;
};

/* 健康状态 → 展示(颜色语义收敛到既有 token, 不加新视觉体系) */
const RUNTIME_LABEL: Record<string, string> = {
  online: "在线", stale: "心跳滞后", offline: "离线", disabled: "已停用",
};

const HEALTH_LABEL: Record<string, string> = {
  healthy: "正常", idle: "空闲", backlogged: "积压",
  stalled: "停滞", degraded: "降级", unavailable: "暂不可用",
};
const HEALTH_CLASS: Record<string, string> = {
  healthy: "ok", idle: "idle", backlogged: "busy",
  stalled: "bad", degraded: "busy", unavailable: "bad",
};

function Dot({ kind }: { kind: string }) {
  return <span className={`pipe-dot ${kind === "ok" ? "ok" : kind === "bad" ? "bad" : "warn"}`} aria-hidden />;
}

function Metric({ label, total, today }: { label: string; total: number | null; today?: number | null }) {
  // total=null → 该 section 不可用: 明确标出, 不显示 0
  return (
    <div className="pipe-metric">
      <span className="pipe-metric-label">{label}</span>
      <span className="pipe-metric-val">{total === null ? "暂不可用" : fmt(total)}</span>
      {total !== null && today !== undefined && today !== null && <span className="pipe-metric-label">今日 +{fmt(today)}</span>}
    </div>
  );
}

function MetaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="pipe-meta-line">
      <span className="pipe-metric-label">{label}</span>
      <span className="pipe-metric-val">{value}</span>
    </div>
  );
}

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

/* error 行: 复活带确认 + 明确条数; 失败不炸页面数据 */
function ErrorRow({ block, onRevive, reviving, reviveNote }: {
  block: ChainBlock; onRevive: () => void; reviving: boolean; reviveNote: string | null;
}) {
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
        {reviving ? "复活中…" : `复活全部 ${total > 0 ? `(${fmt(total)} 条)` : ""}`}
      </button>
      {reviveNote && <span className="pipe-revive-note">{reviveNote}</span>}
    </div>
  );
}

export function SamelabsPipeline() {
  const [data, setData] = useState<Pipeline | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("initial_loading");
  const [lastSuccessAt, setLastSuccessAt] = useState<Date | null>(null);
  const [initialError, setInitialError] = useState("");
  const [reviving, setReviving] = useState<"cb" | "pb" | null>(null);
  const [reviveNote, setReviveNote] = useState<string | null>(null);
  const [confirmChain, setConfirmChain] = useState<"cb" | "pb" | null>(null);
  const aliveRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await apiGet<Pipeline>("/admin/pipeline");
      if (!aliveRef.current) return;
      setData(d);
      setLastSuccessAt(new Date());
      setPhase("ready");
      setInitialError("");
    } catch (err) {
      if (!aliveRef.current) return;
      if (dataRef.current === null) {
        // 首次加载失败: 完整 error state
        setInitialError(err instanceof ApiError && (err.status === 401 || err.status === 403) ? t.admin.noPermission : t.admin.errLoadFailed);
        setPhase("initial_loading");
      } else {
        // 已有成功数据: 保留, 顶部轻提示
        setPhase("stale");
      }
    }
  }, []);

  const dataRef = useRef<Pipeline | null>(null);
  dataRef.current = data;

  useEffect(() => {
    aliveRef.current = true;
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => { aliveRef.current = false; window.clearInterval(id); };
  }, [load]);

  const revive = async (chain: "cb" | "pb") => {
    setConfirmChain(null);
    setReviving(chain);
    try {
      const r = await apiPost<{ chain: string; revived: number }>(`/admin/pipeline/${chain}/errors/revive`);
      setReviveNote(`已复活 ${fmt(r.revived)} 条`);
      await load();
    } catch {
      // 复活失败: 只提示, 主数据不动
      setReviveNote("复活失败，请重试");
    } finally {
      setReviving(null);
    }
  };

  /* ── 首次加载失败: 完整 error state (含重试) ── */
  if (initialError) return <div className="notice error">
    {initialError}
    <button type="button" className="pipe-retry-btn" onClick={() => { setInitialError(""); setPhase("initial_loading"); load(); }}>{t.admin.retryNow}</button>
  </div>;
  if (!data) return <p className="context-loading">{t.common.loading}</p>;

  const loc = (code: string): LocaleRow | undefined => data.cb.locales.find((x) => x.locale === code);
  const zh = loc("zh-CN");
  const others = OTHER_LOCALES.map(loc).filter((x): x is LocaleRow => Boolean(x));
  const othersTotal = others.reduce((a, b) => a + b.total, 0);
  const othersToday = others.reduce((a, b) => a + b.today, 0);

  const gateChip = (gate: Gate) =>
    gate && gate.silent
      ? <span className="pipe-chip silent">静默中 · 剩 {mins(gate.silent_remaining_s)}</span>
      : gate && gate.streak > 0
        ? <span className="pipe-chip retry">连击 {gate.streak}</span>
        : null;

  const healthBadge = (h: Health) => (
    <span className={"pipe-status-line " + (HEALTH_CLASS[h.status] === "ok" ? "" : HEALTH_CLASS[h.status] === "idle" ? "idle" : "")}>
      <Dot kind={HEALTH_CLASS[h.status]} /> {HEALTH_LABEL[h.status] ?? h.status}
      {h.reasons.length > 0 && <span className="pipe-health-reasons" title={h.reasons.join("；")}>{h.reasons[0]}</span>}
    </span>
  );

  const chainHead = (label: string, gate: Gate, h: Health, aging: Aging) => (
    <div className="pipe-chain-head">
      <span className="dashboard-card-label">{label}</span>
      {gateChip(gate)}
      {healthBadge(h)}
      <span className="pipe-aging" title="最老排队任务等待时间">
        排队最久 {aging.oldest_queued_age_s != null ? dur(aging.oldest_queued_age_s) : "—"}
      </span>
    </div>
  );

  const supWrap = data.supplier;
  const sup = supWrap.available ? supWrap.value : null;
  const seedWrap = data.cb.seed;
  const seed = seedWrap.available ? seedWrap.value : null;
  const negWrap = data.cb.negative;
  const neg = negWrap.available ? negWrap.value : null;

  return <>
    <header className="page-title">
      <h1>{t.admin.pipelineTitle}</h1>
      <p>{t.admin.pipelineDesc(REFRESH_MS / 1000, hm(data.generated_at))}</p>
      <div className="pipe-snapshot-line">
        <span>统计快照 {hm(data.stats.generated_at)}（{t.admin.statsAge(data.stats.age_seconds)}{data.stats.stale ? ` · ${t.admin.statsStale}` : ""}）</span>
        {phase === "refreshing" && <span className="pipe-phase">{t.admin.refreshing}</span>}
      </div>
    </header>

    {/* 刷新失败: 轻提示 + 立即重试, 数据保留 */}
    {phase === "stale" && (
      <div className="notice warn pipe-stale-banner">
        {t.admin.refreshFailed(lastSuccessAt ? hm(lastSuccessAt.toISOString()) : "—")}
        <button type="button" className="pipe-retry-btn" onClick={() => { setPhase("refreshing"); load(); }}>{t.admin.retryNow}</button>
      </div>
    )}

    <section className="dashboard-section">
      <div className="dashboard-grid pipe-grid-2">

        {/* ── CB 链 · ChemicalBook ── */}
        <div className="dashboard-card pipe-chain">
          {chainHead("CB 链 · ChemicalBook", data.gates.cb, data.cb.health, data.cb.aging)}

          <Group title="队列">
            <Metric label="排队" total={data.cb.queue.queued} />
            <Metric label="在途" total={data.cb.queue.leased} />
            <Metric label="留痕" total={data.cb.queue.error} />
            <Metric label="近 1 小时入库" total={data.cb.rate_1h} />
          </Group>
          <MetaLine label="最近成功入库" value={hm(data.cb.latest_at)} />
          <MetaLine label="最老排队年龄" value={dur(data.cb.aging.oldest_queued_age_s)} />

          <Group title="落库" note="五语种">
            <Metric label="中文" total={zh ? zh.total : 0} today={zh ? zh.today : 0} />
            <Metric label="其他语种合计" total={othersTotal} today={othersToday} />
            <Metric label="全链合计" total={data.cb.rows.total} today={data.cb.rows.today} />
          </Group>
          <div className="pipe-metrics pipe-sub">
            {others.map((l) => (
              <Metric key={l.locale} label={LOCALE_NAME[l.locale] ?? l.locale} total={l.total} today={l.today} />
            ))}
          </div>

          <ErrorRow block={data.cb} onRevive={() => setConfirmChain("cb")} reviving={reviving === "cb"} reviveNote={confirmChain === "cb" ? null : reviveNote} />
        </div>

        {/* ── PB 链 · PubChem PUG View ── */}
        <div className="dashboard-card pipe-chain">
          {chainHead("PB 链 · PubChem PUG View", data.gates.pubchem, data.pb.health, data.pb.aging)}

          <Group title="队列">
            <Metric label="排队" total={data.pb.queue.queued} />
            <Metric label="在途" total={data.pb.queue.leased} />
            <Metric label="留痕" total={data.pb.queue.error} />
            <Metric label="近 1 小时入库" total={data.pb.rate_1h} />
          </Group>
          <MetaLine label="最近成功入库" value={hm(data.pb.latest_at)} />
          <MetaLine label="最老排队年龄" value={dur(data.pb.aging.oldest_queued_age_s)} />

          <Group title="落库">
            <Metric label="收录条目" total={data.pb.rows.total} today={data.pb.rows.today} />
          </Group>

          <ErrorRow block={data.pb} onRevive={() => setConfirmChain("pb")} reviving={reviving === "pb"} reviveNote={confirmChain === "pb" ? null : reviveNote} />
        </div>
      </div>
    </section>

    {/* ── CB secondary diagnostics(降级区): 供应商 / 账本 / 负面 ── */}
    <section className="dashboard-section pipe-secondary">
      <div className="section-heading"><h2>CB 诊断</h2></div>
      <div className="dashboard-grid pipe-grid-2">
        <div className="dashboard-card pipe-chain">
          <Group title="上游账本" note="来源未命中">
            <Metric label="待处理" total={seed ? seed.accepted : null} />
            <Metric label="已入队" total={seed ? seed.enqueued : null} />
            <Metric label="悬案" total={seed ? seed.ambiguous : null} />
            <Metric label="来源未命中" total={neg ? neg.total : null} today={neg ? neg.today : null} />
          </Group>
          {!seedWrap.available && <div className="pipe-section-unavailable">{t.admin.sectionUnavailable}{seedWrap.error ? `（${seedWrap.error}）` : ""}</div>}
          {negWrap && !negWrap.available && <div className="pipe-section-unavailable">{t.admin.sectionUnavailable}（来源未命中）{negWrap.error ? `（${negWrap.error}）` : ""}</div>}
        </div>
        <div className="dashboard-card pipe-chain">
          <Group title="供应侧">
            <Metric label="供应信息" total={sup ? sup.total_rows : null} today={sup ? sup.today_rows : null} />
            <Metric label="供应商" total={sup ? sup.profiles : null} today={sup ? sup.today_profiles : null} />
          </Group>
          {!supWrap.available && <div className="pipe-section-unavailable">{t.admin.sectionUnavailable}{supWrap.error ? `（${supWrap.error}）` : ""}</div>}
        </div>
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>Worker</h2></div>
      <div className="pipe-table" role="table">
        <div className="pipe-tr pipe-th pipe-tr-5" role="row">
          <span>Worker</span><span>名称</span><span>任务职责</span><span>运行状态</span><span>最近心跳</span>
        </div>
        {data.workers.length === 0
          ? <div className="pipe-tr pipe-tr-5" role="row"><span className="pipe-empty">暂无 worker</span></div>
          : data.workers.map((w) => (
            <div className="pipe-tr pipe-tr-5" role="row" key={w.worker_id}>
              <span className="pipe-locale">{w.worker_id}</span>
              <span>{w.display_name ?? "—"}</span>
              <span className="pipe-src">{w.scopes.map((s) => SCOPE_LABEL[s] ?? s).join(" / ") || "—"}</span>
              <span><Dot kind={w.runtime === "online" ? "ok" : w.runtime === "disabled" ? "warn" : "bad"} />
                {" "}{RUNTIME_LABEL[w.runtime] ?? w.runtime}
              </span>
              <span className="pipe-time" title={w.last_seen_age_s != null ? `${Math.round(w.last_seen_age_s)} 秒前` : ""}>{hm(w.last_seen_at)}</span>
            </div>
          ))}
      </div>
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>CB 链最新 10 条</h2></div>
      <LatestTable rows={data.latest.cb} chain="CB" />
    </section>

    <section className="dashboard-section">
      <div className="section-heading"><h2>PB 链最新 10 条</h2></div>
      <LatestTable rows={data.latest.pb} chain="PB" />
    </section>

    {/* 复活确认对话框(轻量, 不引状态库) */}
    {confirmChain && (() => {
      const block = confirmChain === "cb" ? data.cb : data.pb;
      const n = Object.values(block.error_buckets).reduce((a, b) => a + b, 0);
      return (
        <div className="pipe-confirm" role="alertdialog" aria-modal>
          <div className="pipe-confirm-box">
            <p>{t.admin.reviveConfirm(confirmChain.toUpperCase(), fmt(n))}</p>
            <div className="pipe-confirm-actions">
              <button type="button" className="button" onClick={() => revive(confirmChain)} disabled={n === 0}>确认复活</button>
              <button type="button" className="pipe-revive-btn" onClick={() => setConfirmChain(null)}>取消</button>
            </div>
          </div>
        </div>
      );
    })()}
  </>;
}
