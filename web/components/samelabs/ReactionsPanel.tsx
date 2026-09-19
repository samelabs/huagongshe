"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet, apiPatch, ApiError } from "@/lib/api";
import t from "@/lib/i18n";
import { PAGE_SIZE, parseAdminPage, adminOffset, adminTotalPages } from "@/lib/adminPagination";
import { AdminPagination } from "@/components/samelabs/AdminPagination";

type ReactionRow = { id: number; reaction_smiles: string; visibility: string; moderation_status: "visible" | "hidden"; username: string; display_name: string; created_at: string };
type AdminReactionsResponse = { total: number; items: ReactionRow[] };

type StatusFilter = "all" | "visible" | "hidden";

const STATUS_LABEL: Record<StatusFilter, string> = { all: "全部", visible: "可见", hidden: "隐藏" };

export function SamelabsReactions() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL 是唯一已应用真相源: status / page
  const rawStatus = searchParams.get("status");
  const status: StatusFilter = rawStatus === "visible" || rawStatus === "hidden" ? rawStatus : "all";
  const page = parseAdminPage(searchParams.get("page"));

  const [reactions, setReactions] = useState<ReactionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const seqRef = useRef(0);
  const statusRef = useRef(status);
  const pageRef = useRef(page);
  statusRef.current = status;
  pageRef.current = page;

  // URL 状态驱动加载; 超界 clamp
  useEffect(() => {
    const seq = ++seqRef.current;
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(adminOffset(page)) });
    if (status !== "all") params.set("status", status);
    apiGet<AdminReactionsResponse>(`/admin/reactions?${params}`).then((data) => {
      if (seq !== seqRef.current) return;
      setReactions(data.items);
      setTotal(data.total);
      setError("");
      const totalPages = adminTotalPages(data.total, PAGE_SIZE);
      if (data.total > 0 && page > totalPages) {
        const next = new URLSearchParams();
        if (status !== "all") next.set("status", status);
        next.set("page", String(totalPages));
        router.replace(`/samelabs/reactions?${next}`);
        return;
      }
      if (data.total === 0 && page > 1) {
        // 空集合: canonical 回第 1 页 (只 replace 一次, 不产生环)
        const next = new URLSearchParams();
        if (status !== "all") next.set("status", status);
        const qs = next.toString();
        router.replace(qs ? `/samelabs/reactions?${qs}` : "/samelabs/reactions");
        return;
      }
    }).catch((e) => {
      if (seq !== seqRef.current) return;
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    }).finally(() => {
      if (seq === seqRef.current) setLoading(false);
    });
  }, [status, page, router]);

  function navigateTo(nextStatus: StatusFilter, nextPage: number, push = false) {
    const next = new URLSearchParams();
    if (nextStatus !== "all") next.set("status", nextStatus);
    if (nextPage > 1) next.set("page", String(nextPage));
    const qs = next.toString();
    const url = qs ? `/samelabs/reactions?${qs}` : "/samelabs/reactions";
    if (push) router.push(url); else router.replace(url);
  }

  function setStatusFilter(s: StatusFilter) {
    if (s === status) return;
    navigateTo(s, 1); // 切 filter 回第 1 页
  }

  // mutation 后 reload 当前 URL filter/page; filtered 集合变化导致空页时回最后有效页
  async function reload() {
    const seq = ++seqRef.current;
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(adminOffset(pageRef.current)) });
    if (statusRef.current !== "all") params.set("status", statusRef.current);
    try {
      const data = await apiGet<AdminReactionsResponse>(`/admin/reactions?${params}`);
      if (seq !== seqRef.current) return;
      setReactions(data.items);
      setTotal(data.total);
      setError("");
      const totalPages = adminTotalPages(data.total, PAGE_SIZE);
      if (data.total > 0 && pageRef.current > totalPages) {
        // 当前页被 mutation 清空(如 visible filter 下隐藏最后一行) → 回最后有效页
        const next = new URLSearchParams();
        if (statusRef.current !== "all") next.set("status", statusRef.current);
        next.set("page", String(totalPages));
        router.replace(`/samelabs/reactions?${next}`);
        return;
      }
      if (data.total === 0 && pageRef.current > 1) {
        const next = new URLSearchParams();
        if (statusRef.current !== "all") next.set("status", statusRef.current);
        const qs = next.toString();
        router.replace(qs ? `/samelabs/reactions?${qs}` : "/samelabs/reactions");
      }
    } catch (e) {
      if (seq !== seqRef.current) return;
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errOperation);
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }

  async function toggle(id: number, current: "visible" | "hidden") {
    setError(""); setBusyId(id);
    try {
      await apiPatch(`/admin/reactions/${id}/moderation`, JSON.stringify({ status: current === "visible" ? "hidden" : "visible" }));
      await reload();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  if (error && reactions.length === 0 && !loading) return <div className="notice error">{error}</div>;

  return <>
    <header className="page-title">
      <h1>{t.admin.reactionsTitle}</h1>
    </header>
        {error && <div className="notice error">{error}</div>}
        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.reactionsListTitle}</h2></div>
            <span>{`共 ${total} 条`}</span>
          </div>
          <div className="admin-filters">
            {(["all", "visible", "hidden"] as const).map((s) => (
              <button key={s} className={status === s ? "active" : ""}
                onClick={() => setStatusFilter(s)}>
                {STATUS_LABEL[s]}
              </button>
            ))}
          </div>
          <div className="admin-table reaction-admin-list">
            {reactions.map((r) => <article key={r.id}>
              <div>
                <EntityId kind="reaction" id={r.id} />
                <span>{r.display_name} · {r.visibility === "public" ? t.admin.publicLabel : t.admin.privateLabel}</span>
              </div>
              <span className={`status ${r.moderation_status}`}>{r.moderation_status === "visible" ? t.admin.statusVisible : t.admin.statusHidden}</span>
              <button className="text-button" disabled={busyId === r.id} onClick={() => toggle(r.id, r.moderation_status)}>
                {busyId === r.id ? "…" : r.moderation_status === "visible" ? t.admin.actionHide : t.admin.actionShow}
              </button>
            </article>)}
            {!loading && reactions.length === 0 && (
              <div className="admin-empty">{status === "all" ? "暂无用户反应" : "当前筛选下没有反应"}</div>
            )}
          </div>
          <AdminPagination page={page} total={total} pageSize={PAGE_SIZE} loading={loading}
            onPageChange={(p) => navigateTo(status, p, p > page)} />
        </section>
  </>;
}
