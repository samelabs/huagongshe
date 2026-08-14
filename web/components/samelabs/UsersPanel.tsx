"use client";

import { useEffect, useState } from "react";
import { SamelabsNav } from "@/components/SamelabsNav";
import { apiGet, apiPatch, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type UserRow = { id: number; username: string; display_name: string; email: string; role: string; status: "active" | "disabled"; created_at: string; last_login_at: string | null };

export function SamelabsUsers() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  async function reload() {
    try {
      const data = await apiGet<UserRow[]>(`/admin/users?limit=100`);
      setUsers(data);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
    }
  }

  useEffect(() => {
    let active = true;
    apiGet<UserRow[]>(`/admin/users?limit=100`).then((data) => {
      if (active) setUsers(data);
    }).catch((err) => {
      if (!active) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
    });
    return () => { active = false; };
  }, []);

  async function toggle(id: number, status: "active" | "disabled") {
    setError(""); setBusyId(id);
    try {
      await apiPatch(`/admin/users/${id}/status`, JSON.stringify({ status: status === "active" ? "disabled" : "active" }));
      await reload();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  async function toggleRole(id: number, role: string) {
    setError(""); setBusyId(id);
    try {
      await apiPatch(`/admin/users/${id}/role`, JSON.stringify({ role: role === "admin" ? "member" : "admin" }));
      await reload();
    } catch {
      setError(t.admin.errOperation);
    } finally { setBusyId(null); }
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
