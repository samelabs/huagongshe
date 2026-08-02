"use client";

import { useEffect, useState } from "react";
import { SamelabsNav } from "@/components/SamelabsNav";
import t from "@/lib/i18n";

type UserRow = { id: number; username: string; display_name: string; email: string; role: string; status: "active" | "disabled"; created_at: string; last_login_at: string | null };

export function SamelabsUsers() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  async function load() {
    const res = await fetch("/api/admin/users?limit=100", { cache: "no-store" });
    if (res.status === 401 || res.status === 403) { setError(t.admin.noPermission); return; }
    if (res.ok) setUsers(await res.json());
  }

  useEffect(() => { load(); }, []);

  async function toggle(id: number, status: "active" | "disabled") {
    setError(""); setBusyId(id);
    try {
      const res = await fetch(`/api/admin/users/${id}/status`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: status === "active" ? "disabled" : "active" }),
      });
      if (!res.ok) throw new Error();
      await load();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  async function toggleRole(id: number, role: string) {
    setError(""); setBusyId(id);
    try {
      const res = await fetch(`/api/admin/users/${id}/role`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: role === "admin" ? "member" : "admin" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        setError(err?.detail || t.admin.errOperation); return;
      }
      await load();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  if (error && users.length === 0) return <div className="notice error">{error}</div>;

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.usersKicker}</p>
      <h1>{t.admin.usersTitle}</h1>
    </header>
    <div className="settings-layout">
      <SamelabsNav />
      <div className="settings-content">
        {error && <div className="notice error">{error}</div>}
        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.usersAll}</h2></div>
            <span>{t.admin.userCount(users.length)}</span>
          </div>
          <div className="admin-table">
            {users.map((u) => <article key={u.id}>
              <div>
                <strong>{u.display_name}</strong>
                <span>@{u.username} · {u.email}</span>
              </div>
              <div className="admin-user-badges">
                <span className={`status ${u.status}`}>{u.status === "active" ? t.admin.statusActive : t.admin.statusDisabled}</span>
                <span className={`status ${u.role === "admin" ? "admin" : ""}`}>{u.role === "admin" ? t.admin.roleAdmin : t.admin.roleMember}</span>
              </div>
              <div className="admin-user-actions">
                <button className="text-button" disabled={busyId === u.id} onClick={() => toggleRole(u.id, u.role)}>
                  {busyId === u.id ? "…" : u.role === "admin" ? t.admin.actionRemoveAdmin : t.admin.actionSetAdmin}
                </button>
                <button className="text-button" disabled={busyId === u.id} onClick={() => toggle(u.id, u.status)}>
                  {busyId === u.id ? "…" : u.status === "active" ? t.admin.actionDisable : t.admin.actionEnable}
                </button>
              </div>
            </article>)}
          </div>
        </section>
      </div>
    </div>
  </>;
}
