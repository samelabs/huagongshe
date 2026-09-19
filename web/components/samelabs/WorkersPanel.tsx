"use client";

import { useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type WorkerRow = {
  worker_id: string;
  display_name: string;
  scopes: string[];
  max_lease_jobs: number;
  enabled: boolean;
  created_at: string;
  last_seen_at: string | null;
  disabled_at: string | null;
  runtime: string;
};

type IssueResult = {
  worker_id: string;
  token: string;
  env: Record<string, string>;
};

const KNOWN_SCOPES = ["pubchem", "cas"] as const;

const SCOPE_LABEL: Record<string, string> = {
  pubchem: "PubChem",
  cas: "ChemicalBook",
};

const RUNTIME_LABEL: Record<string, string> = {
  online: "在线",
  stale: "心跳滞后",
  offline: "离线",
  disabled: "已停用",
};

function fmtDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleString("zh-CN") : "—";
}

export function SamelabsWorkers() {
  const [workers, setWorkers] = useState<WorkerRow[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState("");
  const [workerId, setWorkerId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["pubchem"]);
  const [issued, setIssued] = useState<IssueResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [pendingDisableWorker, setPendingDisableWorker] = useState<WorkerRow | null>(null);
  const [pendingDeleteWorker, setPendingDeleteWorker] = useState<WorkerRow | null>(null);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;
    apiGet<WorkerRow[]>("/admin/workers").then((data) => {
      if (active) setWorkers(data);
    }).catch((err) => {
      if (!active) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    });
    return () => { active = false; };
  }, []);

  async function reload() {
    try {
      setWorkers(await apiGet<WorkerRow[]>("/admin/workers"));
    } catch { setError(t.admin.errLoadFailed); }
  }

  function toggleScope(scope: string) {
    setScopes((prev) => prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]);
  }

  async function issue(event: React.FormEvent) {
    event.preventDefault();
    setFormError("");
    if (scopes.length === 0) { setFormError(t.admin.workerScopeRequired); return; }
    try {
      const result = await apiPost<IssueResult>("/admin/workers", JSON.stringify({
        worker_id: workerId.trim(),
        display_name: displayName.trim(),
        scopes,
        max_lease_jobs: 4,
      }));
      setIssued(result);
      setShowForm(false);
      setWorkerId(""); setDisplayName(""); setScopes(["pubchem"]);
      await reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setFormError(t.admin.workerExists);
      else setFormError(t.admin.errOperation);
    }
  }

  async function setEnabled(row: WorkerRow, enabled: boolean) {
    setError(""); setBusyId(row.worker_id);
    try {
      await apiPatch(`/admin/workers/${row.worker_id}`, JSON.stringify({ enabled }));
      await reload();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  async function confirmDisableWorker() {
    if (!pendingDisableWorker) return;
    const row = pendingDisableWorker;
    setPendingDisableWorker(null);
    await setEnabled(row, false);
  }

  async function confirmDeleteWorker() {
    if (!pendingDeleteWorker) return;
    const row = pendingDeleteWorker;
    setPendingDeleteWorker(null);
    setError(""); setBusyId(row.worker_id);
    try {
      await apiDelete(`/admin/workers/${row.worker_id}`);
      await reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(e.detail || t.admin.workerDeleteBlockedFallback);
      } else {
        setError(t.admin.errOperation);
      }
    } finally { setBusyId(null); }
  }

  async function copyEnv() {
    if (!issued) return;
    const text = Object.entries(issued.env)
      .map(([k, v]) => `${k}=${v}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (resetTimer.current) clearTimeout(resetTimer.current);
      resetTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch { /* 剪贴板不可用时用户手动复制 */ }
  }

  useEffect(() => () => { if (resetTimer.current) clearTimeout(resetTimer.current); }, []);

  if (error && workers.length === 0) return <div className="notice error">{error}</div>;

  return <>
    <header className="page-title">
      <h1>{t.admin.workersTitle}</h1>
      <p>{t.admin.workersIntro}</p>
    </header>
    {error && <div className="notice error">{error}</div>}

    {issued && (
      <section className="dashboard-section">
        <div className="section-heading">
          <div><h2>{issued.worker_id} · {t.admin.workerTokenOnce}</h2></div>
          <button className="text-button" onClick={copyEnv}>{copied ? t.admin.workerCopied : t.admin.workerCopyEnv}</button>
        </div>
        <pre className="admin-pre"><code>{Object.entries(issued.env).map(([k, v]) => `${k}=${v}`).join("\n")}</code></pre>
      </section>
    )}

    <section className="dashboard-section">
      <div className="section-heading">
        <div><h2>{t.admin.workersAll}</h2></div>
        <button className="text-button" onClick={() => { setShowForm(!showForm); setFormError(""); }}>{t.admin.workerIssue}</button>
      </div>

      {showForm && (
        <form className="admin-worker-form" onSubmit={issue}>
          <label>{t.admin.workerId}
            <input value={workerId} onChange={(e) => setWorkerId(e.target.value)} required
              minLength={3} maxLength={64} pattern="[a-z0-9][a-z0-9-]*" placeholder="gpu-box-1" />
          </label>
          <label>{t.admin.workerDisplayName}
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required
              minLength={1} maxLength={80} placeholder="GPU 抓取节点" />
          </label>
          <fieldset>
            <legend>{t.admin.workerScopes}</legend>
            {KNOWN_SCOPES.map((scope) => (
              <label key={scope} className="checkbox-row">
                <input type="checkbox" checked={scopes.includes(scope)} onChange={() => toggleScope(scope)} />
                <span>{SCOPE_LABEL[scope] ?? scope}</span>
              </label>
            ))}
          </fieldset>
          {formError && <div className="notice error">{formError}</div>}
          <button type="submit" className="button primary">{t.admin.workerIssueConfirm}</button>
        </form>
      )}

      <div className="admin-table">
        {workers.map((w) => <article key={w.worker_id}>
          <div>
            <strong>{w.display_name}</strong>
            <span>{w.worker_id} · {w.scopes.map((s) => SCOPE_LABEL[s] ?? s).join(" / ") || "—"} · {t.admin.workerMaxLease(w.max_lease_jobs)}</span>
            <span>{w.last_seen_at ? t.admin.workerLastSeen(new Date(w.last_seen_at).toLocaleString()) : t.admin.workerNeverSeen}</span>
            <span>{t.admin.workerCreated(fmtDate(w.created_at))}</span>
          </div>
          <div className="admin-user-badges">
            <span className={`status ${w.enabled ? "active" : "disabled"}`}>
              {w.enabled ? t.admin.workerEnabled : t.admin.workerDisabled}
            </span>
            <span className={`status ${w.runtime === "online" ? "active" : w.runtime === "disabled" ? "disabled" : ""}`}>
              {RUNTIME_LABEL[w.runtime] ?? w.runtime}
            </span>
          </div>
          <div className="admin-user-actions">
            <button className="text-button" disabled={busyId === w.worker_id}
              onClick={() => w.enabled ? setPendingDisableWorker(w) : setEnabled(w, true)}>
              {busyId === w.worker_id ? "…" : w.enabled ? t.admin.actionDisable : t.admin.actionEnable}
            </button>
            <button className="text-button" disabled={busyId === w.worker_id}
              onClick={() => setPendingDeleteWorker(w)}>
              {t.admin.actionDelete}
            </button>
          </div>
        </article>)}
      </div>
    </section>

    {pendingDisableWorker && (
      <div className="pipe-confirm" role="dialog" aria-modal onClick={() => setPendingDisableWorker(null)}>
        <div className="pipe-confirm-box" onClick={(e) => e.stopPropagation()}>
          <p>{t.admin.workerDisableConfirm(pendingDisableWorker.display_name, pendingDisableWorker.worker_id)}</p>
          <p>{t.admin.workerDisableEffect}</p>
          <div className="pipe-confirm-actions">
            <button type="button" className="button small" onClick={() => setPendingDisableWorker(null)}>{t.admin.cancel}</button>
            <button type="button" className="button danger small" disabled={busyId === pendingDisableWorker.worker_id}
              onClick={confirmDisableWorker}>{t.admin.actionDisable}</button>
          </div>
        </div>
      </div>
    )}

    {pendingDeleteWorker && (
      <div className="pipe-confirm" role="dialog" aria-modal onClick={() => setPendingDeleteWorker(null)}>
        <div className="pipe-confirm-box" onClick={(e) => e.stopPropagation()}>
          <p>{t.admin.workerDeleteConfirm(pendingDeleteWorker.display_name, pendingDeleteWorker.worker_id)}</p>
          <p>{t.admin.workerDeleteEffect}</p>
          <div className="pipe-confirm-actions">
            <button type="button" className="button small" onClick={() => setPendingDeleteWorker(null)}>{t.admin.cancel}</button>
            <button type="button" className="button danger small" disabled={busyId === pendingDeleteWorker.worker_id}
              onClick={confirmDeleteWorker}>{t.admin.actionDelete}</button>
          </div>
        </div>
      </div>
    )}
  </>;
}
