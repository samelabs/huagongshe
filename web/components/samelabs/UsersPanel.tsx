"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiGet, apiPatch, ApiError } from "@/lib/api";
import t from "@/lib/i18n";
import { PAGE_SIZE, parseAdminPage, adminOffset, adminTotalPages } from "@/lib/adminPagination";
import { AdminPagination } from "@/components/samelabs/AdminPagination";

type UserRow = { id: number; username: string; display_name: string; email: string; role: string; status: "active" | "disabled"; created_at: string; last_login_at: string | null };
type AdminUsersResponse = { total: number; items: UserRow[] };

export function SamelabsUsers() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL 是唯一已应用真相源: q / page
  const appliedQ = searchParams.get("q") ?? "";
  const page = parseAdminPage(searchParams.get("page"));

  const [users, setUsers] = useState<UserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [q, setQ] = useState(appliedQ);          // draft: 输入框当前值
  const [pendingDisable, setPendingDisable] = useState<UserRow | null>(null);
  const [pendingRole, setPendingRole] = useState<UserRow | null>(null);

  // draft 与 URL 同步: 返回/前进后退到新 q 时刷新输入框
  useEffect(() => { setQ(appliedQ); }, [appliedQ]);

  // 请求竞态防护: 只接受最新一次请求的结果
  const seqRef = useRef(0);

  const appliedQRef = useRef(appliedQ);
  const pageRef = useRef(page);
  appliedQRef.current = appliedQ;
  pageRef.current = page;

  // URL 状态驱动加载; 超界时 clamp 到最后有效页(通过 URL 导航, 不直接 set)
  useEffect(() => {
    const seq = ++seqRef.current;
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(adminOffset(page)) });
    if (appliedQ.trim()) params.set("q", appliedQ.trim());
    apiGet<AdminUsersResponse>(`/admin/users?${params}`).then((data) => {
      if (seq !== seqRef.current) return; // 过期响应丢弃
      setUsers(data.items);
      setTotal(data.total);
      setError("");
      const totalPages = adminTotalPages(data.total, PAGE_SIZE);
      if (data.total > 0 && page > totalPages) {
        // 超界: 导航到最后有效页, 由 URL 变化触发重载 (不会死循环: 页数只减不增)
        const next = new URLSearchParams();
        if (appliedQ.trim()) next.set("q", appliedQ.trim());
        next.set("page", String(totalPages));
        router.replace(`/samelabs/users?${next}`);
        return;
      }
      if (data.total === 0 && page > 1) {
        // 空集合: canonical 回第 1 页 (total=0 时 totalPages=1, 只 replace 一次)
        const next = new URLSearchParams();
        if (appliedQ.trim()) next.set("q", appliedQ.trim());
        const qs = next.toString();
        router.replace(qs ? `/samelabs/users?${qs}` : "/samelabs/users");
        return;
      }
    }).catch((e) => {
      if (seq !== seqRef.current) return;
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    }).finally(() => {
      if (seq === seqRef.current) setLoading(false);
    });
  }, [appliedQ, page, router]);

  // URL 写入: 只维护本页已知参数, 默认值省略
  function navigateTo(nextQ: string, nextPage: number, push = false) {
    const next = new URLSearchParams();
    if (nextQ.trim()) next.set("q", nextQ.trim());
    if (nextPage > 1) next.set("page", String(nextPage));
    const qs = next.toString();
    const url = qs ? `/samelabs/users?${qs}` : "/samelabs/users";
    if (push) router.push(url); else router.replace(url);
  }

  // 搜索提交: 应用 draft, 回第 1 页
  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    navigateTo(q, 1);
  }

  // mutation 后 reload 当前 URL filter/page (URL 未变, 直接重拉)
  async function reload() {
    const seq = ++seqRef.current;
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(adminOffset(pageRef.current)) });
    if (appliedQRef.current.trim()) params.set("q", appliedQRef.current.trim());
    try {
      const data = await apiGet<AdminUsersResponse>(`/admin/users?${params}`);
      if (seq !== seqRef.current) return;
      setUsers(data.items);
      setTotal(data.total);
      setError("");
      // mutation 可能清空当前页(如最后一条被停用不影响集合, 但搜索词变化场景): clamp
      const totalPages = adminTotalPages(data.total, PAGE_SIZE);
      if (data.total > 0 && pageRef.current > totalPages) {
        const next = new URLSearchParams();
        if (appliedQRef.current.trim()) next.set("q", appliedQRef.current.trim());
        next.set("page", String(totalPages));
        router.replace(`/samelabs/users?${next}`);
        return;
      }
      if (data.total === 0 && pageRef.current > 1) {
        const next = new URLSearchParams();
        if (appliedQRef.current.trim()) next.set("q", appliedQRef.current.trim());
        const qs = next.toString();
        router.replace(qs ? `/samelabs/users?${qs}` : "/samelabs/users");
      }
    } catch (e) {
      if (seq !== seqRef.current) return;
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errOperation);
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }

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

  if (error && users.length === 0 && !loading) return <div className="notice error">{error}</div>;

  const totalPages = adminTotalPages(total, PAGE_SIZE);

  return <>
    <header className="page-title">
      <h1>{t.admin.usersTitle}</h1>
    </header>
        {error && <div className="notice error">{error}</div>}
        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.usersAll}</h2></div>
            <span>{appliedQ ? `搜索 "${appliedQ}" · 共 ${total} 条` : `共 ${total} 条`}</span>
          </div>
          <form className="admin-search" onSubmit={submitSearch}>
            <input
              value={q}
              placeholder={t.admin.userSearchPlaceholder}
              onChange={(e) => setQ(e.target.value)}
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
                <button className="text-button" disabled={busyId === u.id} onClick={() => setPendingRole(u)}>
                  {busyId === u.id ? "…" : u.role === "admin" ? t.admin.actionRemoveAdmin : t.admin.actionSetAdmin}
                </button>
                <button className="text-button" disabled={busyId === u.id}
                  onClick={() => u.status === "active" ? setPendingDisable(u) : enable(u.id)}>
                  {busyId === u.id ? "…" : u.status === "active" ? t.admin.actionDisable : t.admin.actionEnable}
                </button>
              </div>
            </article>)}
            {!loading && users.length === 0 && (
              <div className="admin-empty">{appliedQ ? "没有匹配的用户" : "暂无用户"}</div>
            )}
          </div>
          <AdminPagination page={page} total={total} pageSize={PAGE_SIZE} loading={loading}
            onPageChange={(p) => navigateTo(appliedQ, p, p > page)} />
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
        {pendingRole && (
          <div className="pipe-confirm" role="dialog" aria-modal onClick={() => setPendingRole(null)}>
            <div className="pipe-confirm-box" onClick={(e) => e.stopPropagation()}>
              <p>{t.admin.userRoleConfirm(
                pendingRole.display_name,
                pendingRole.username,
                pendingRole.role === "admin" ? t.admin.roleAdmin : t.admin.roleMember,
                pendingRole.role === "admin" ? t.admin.roleMember : t.admin.roleAdmin,
              )}</p>
              <p>{pendingRole.role === "admin" ? t.admin.userDemoteEffect : t.admin.userPromoteEffect}</p>
              <div className="pipe-confirm-actions">
                <button type="button" className="button small" onClick={() => setPendingRole(null)}>{t.admin.cancel}</button>
                <button type="button" className="button danger small" disabled={busyId === pendingRole.id}
                  onClick={() => { const row = pendingRole; setPendingRole(null); toggleRole(row.id, row.role); }}>
                  {pendingRole.role === "admin" ? t.admin.actionRemoveAdmin : t.admin.actionSetAdmin}
                </button>
              </div>
            </div>
          </div>
        )}
  </>;
}
