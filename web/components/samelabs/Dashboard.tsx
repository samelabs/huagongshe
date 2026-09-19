"use client";

import { useEffect, useState } from "react";
import { apiGet, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type Dashboard = {
  users: { total: number; today: number; week: number };
  reactions: { user_created: number; today: number };
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
    let active = true;
    apiGet<Dashboard>(`/admin/dashboard`).then((data) => {
      if (active) setData(data);
    }).catch((err) => {
      if (!active) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    });
    return () => { active = false; };
  }, []);

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="context-loading">{t.common.loading}</p>;

  return <>

    <header className="page-title">
      <h1>{t.admin.dashboardTitle}</h1>
    </header>
        <div className="dashboard-grid">
          <StatCard label={t.admin.statUsers} value={fmt(data.users.total)} sub={t.admin.statUsersSub(data.users.today, data.users.week)} />
          <StatCard label={t.admin.statUserReactions} value={fmt(data.reactions.user_created)} sub={t.admin.statUserReactionsSub(data.reactions.today)} />
          <StatCard label={t.admin.statDisk} value={`${data.system.disk_pct}%`} sub={t.admin.statDiskSub(data.system.disk_free_gb, data.system.disk_total_gb)} />
        </div>
  </>;
}
