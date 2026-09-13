"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPatch, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type UserRow = { id: number; username: string; display_name: string; email: string; role: string; status: "active" | "disabled"; created_at: string; last_login_at: string | null };
type AdminUsersResponse = { total: number; items: UserRow[] };

export function SamelabsUsers() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [total, setTotal] = useState(0); // Batch 2 分页控件使用, 本轮不展示
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [q, setQ] = useState("");                       // draft: 输入框当前值
  const [appliedQ, setAppliedQ] = useState("");          // 已应用: 成功加载所对应的搜索条件
  const [pendingDisable, setPendingDisable] = useState<UserRow | null>(null);

  // 仅成功才推进 appliedQ; 失败保持旧值(draft 不参与计数文案)
  async function load(query: string) {
    const params = new URLSearchParams({ limit: "100", offset: "0" });
    if (query.trim()) params.set("q", query.trim());
    try {
      const data = await apiGet<AdminUsersResponse>(`/admin/users?${params}`);
      setUsers(data.items);
      setTotal(data.total);
      setAppliedQ(query.trim());
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
    }
  }

  useEffect(() => {
    let active = true;
    (async () => {
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      try {
        const data = await apiGet<AdminUsersResponse>(`/admin/users?${params}`);
        if (active) { setUsers(data.items); setTotal(data.total); }
      } catch (e) {
        if (!active) return;
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
      }
    })();
    return () => { active = false; };
  }, []);

  async function reload() { await load(appliedQ); }

  async function confirmDisable() {
    if (!pendingDisable) return;
    setError(""); setBusyId(pendingDisable.id);
    try {
      await apiPatch(`/admin/users/${pendingDisable.id}/status`, JSON.stringify({ status: "disabled" }));
      setPendingDisable(null);
      await reload();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  async function enable(id: number) {
    setError(""); setBusyId(id);
    try {
      await apiPatch(`/admin/users/${id}/status`, JSON.stringify({ status: "active" }));
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
        {error && <div className="notice error">{error}</div>}
        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.usersAll}</h2></div>
            <span>{t.admin.userShownCount(users.length, appliedQ || null)}</span>
          </div>
          <form className="admin-search" onSubmit={(e) => { e.preventDefault(); load(q); }}>
            <input
              value={q}
              placeholder={t.admin.userSearchPlaceholder}
              onChange={(e) => { setQ(e.target.value); if (e.target.value === "") load(""); }}
            />
            <button type="submit" className="button small">{t.admin.userSearch}</button>
          </form>
          <div className="admin-table admin-actions-min">
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
                <button className="text-button" disabled={busyId === u.id}
                  onClick={() => u.status === "active" ? setPendingDisable(u) : enable(u.id)}>
                  {busyId === u.id ? "…" : u.status === "active" ? t.admin.actionDisable : t.admin.actionEnable}
                </button>
              </div>
            </article>)}
          </div>
        </section>
        {pendingDisable && (
          <div className="pipe-confirm" role="dialog" aria-modal onClick={() => setPendingDisable(null)}>
            <div className="pipe-confirm-box" onClick={(e) => e.stopPropagation()}>
              <p>{t.admin.userDisableConfirm(pendingDisable.username, pendingDisable.email)}</p>
              <p>{t.admin.userDisableEffect}</p>
              <div className="pipe-confirm-actions">
                <button type="button" className="button small" onClick={() => setPendingDisable(null)}>{t.admin.cancel}</button>
                <button type="button" className="button danger small" disabled={busyId === pendingDisable.id}
                  onClick={confirmDisable}>{t.admin.actionDisable}</button>
              </div>
            </div>
          </div>
        )}
  </>;
}
