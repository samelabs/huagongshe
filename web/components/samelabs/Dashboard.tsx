"use client";

import { useEffect, useState } from "react";
import { SamelabsNav } from "@/components/SamelabsNav";
import t from "@/lib/i18n";

type Dashboard = {
  users: { total: number; today: number; week: number };
  sessions: number;
  tokens: { total: number; active: number };
  reactions: { total: number; user_created: number; today: number };
  chemicals: number;
  system: { disk_total_gb: number; disk_used_gb: number; disk_free_gb: number; disk_pct: number };
};

function fmt(n: number) {
  return new Intl.NumberFormat("zh-CN").format(n);
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="dashboard-card">
    <span className="dashboard-card-label">{label}</span>
    <strong className="dashboard-card-value">{value}</strong>
    {sub && <span className="dashboard-card-sub">{sub}</span>}
  </div>;
}

export function SamelabsDashboard() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/admin/dashboard", { cache: "no-store" }).then(async (r) => {
      if (r.status === 401 || r.status === 403) { setError(t.admin.noPermission); return; }
      if (!r.ok) throw new Error();
      setData(await r.json());
    }).catch(() => setError(t.admin.errLoadFailed));
  }, []);

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="context-loading">正在读取…</p>;

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.dashboardKicker}</p>
      <h1>{t.admin.dashboardTitle}</h1>
    </header>
    <div className="settings-layout">
      <SamelabsNav />
      <div className="settings-content">
        <div className="dashboard-grid">
          <StatCard label={t.admin.statUsers} value={fmt(data.users.total)} sub={t.admin.statUsersSub(data.users.today, data.users.week)} />
          <StatCard label={t.admin.statSessions} value={fmt(data.sessions)} />
          <StatCard label={t.admin.statTokens} value={fmt(data.tokens.active)} sub={t.admin.statTokensSub(data.tokens.total)} />
          <StatCard label={t.admin.statUserReactions} value={fmt(data.reactions.user_created)} sub={t.admin.statUserReactionsSub(data.reactions.today)} />
          <StatCard label={t.admin.statAllReactions} value={fmt(data.reactions.total)} />
          <StatCard label={t.admin.statChemicals} value={fmt(data.chemicals)} />
          <StatCard label={t.admin.statDisk} value={`${data.system.disk_pct}%`} sub={t.admin.statDiskSub(data.system.disk_free_gb, data.system.disk_total_gb)} />
        </div>
      </div>
    </div>
  </>;
}
