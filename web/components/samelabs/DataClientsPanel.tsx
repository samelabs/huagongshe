"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiPatch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";

type ClientRow = {
  id: number; client_id: string; name: string; contact: string;
  scopes: string[]; rate_per_minute: number; rate_per_day: number;
  enabled: boolean; expires_at: string | null; created_at: string;
  calls_today?: number; errors_today?: number;
};

type ListResponse = { items: ClientRow[] };
type CreatedResponse = ClientRow & { token: string };

const SCOPE_OPTIONS = ["data:chemical:read", "data:reaction:read"];

/** 对外数据服务的凭证管理: 发放(令牌只显示一次)、停用/启用、改额度。 */
export function SamelabsDataClients() {
  const [items, setItems] = useState<ClientRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ client_id: string; token: string } | null>(null);
  const [form, setForm] = useState({
    name: "", contact: "", scopes: [SCOPE_OPTIONS[0]],
    rate_per_minute: "60", rate_per_day: "20000",
  });
  const seqRef = useRef(0);

  useEffect(() => {
    const seq = ++seqRef.current;
    apiGet<ListResponse>("/admin/data-clients").then((data) => {
      if (seq !== seqRef.current) return;
      setItems(data.items);
      setError("");
    }).catch(() => {
      if (seq === seqRef.current) setError("凭证列表加载失败");
    });
  }, []);

  function toggleScope(scope: string) {
    setForm((prev) => ({
      ...prev,
      scopes: prev.scopes.includes(scope)
        ? prev.scopes.filter((s) => s !== scope)
        : [...prev.scopes, scope],
    }));
  }

  async function create() {
    if (!form.name.trim() || form.scopes.length === 0) {
      setError("名称与 scope 必填"); return;
    }
    setBusy(true); setError("");
    try {
      const row = await apiPost<CreatedResponse>("/admin/data-clients", JSON.stringify({
        name: form.name.trim(), contact: form.contact.trim(), scopes: form.scopes,
        rate_per_minute: Number(form.rate_per_minute) || 60,
        rate_per_day: Number(form.rate_per_day) || 20000,
      }));
      setIssued({ client_id: row.client_id, token: row.token });
      setForm({ ...form, name: "", contact: "" });
      const data = await apiGet<ListResponse>("/admin/data-clients");
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? (err.detail || "发放失败") : "发放失败");
    } finally { setBusy(false); }
  }

  async function patch(client: ClientRow, body: Record<string, unknown>) {
    setBusy(true);
    try {
      await apiPatch(`/admin/data-clients/${client.id}`, JSON.stringify(body));
      const data = await apiGet<ListResponse>("/admin/data-clients");
      setItems(data.items);
      setError("");
    } catch {
      setError("更新失败");
    } finally { setBusy(false); }
  }

  return <section className="samelabs-panel">
    <h2>数据服务凭证</h2>
    <p className="samelabs-panel-desc">
      面向持授权凭证的对外数据查询接口（/data/v1）。令牌明文只在发放时显示一次。
    </p>

    {error && <Notice tone="err">{error}</Notice>}

    {issued && (
      <div className="token-secret" style={{ marginTop: 12 }}>
        <strong>凭证已发放 — 令牌仅此一次可见，请立即交对接方保存</strong>
        <code className="token-code">{issued.client_id}</code>
        <code className="token-code">{issued.token}</code>
        <Button variant="secondary" size="sm" onClick={() => setIssued(null)}>我已保存</Button>
      </div>
    )}

    <div className="form-fields" style={{ maxWidth: 560 }}>
      <Field label="名称">
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={120} />
      </Field>
      <Field label="联系人">
        <Input value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} maxLength={200} />
      </Field>
      <Field label="scope">
        <div style={{ display: "flex", gap: 12 }}>
          {SCOPE_OPTIONS.map((scope) => (
            <label key={scope} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={form.scopes.includes(scope)} onChange={() => toggleScope(scope)} />
              {scope}
            </label>
          ))}
        </div>
      </Field>
      <div className="form-fields two-columns">
        <Field label="每分钟额度">
          <Input value={form.rate_per_minute} onChange={(e) => setForm({ ...form, rate_per_minute: e.target.value })} inputMode="numeric" />
        </Field>
        <Field label="每天额度">
          <Input value={form.rate_per_day} onChange={(e) => setForm({ ...form, rate_per_day: e.target.value })} inputMode="numeric" />
        </Field>
      </div>
      <Button variant="primary" loading={busy} onClick={() => void create()}>发放凭证</Button>
    </div>

    {items.length > 0 && (
      <table className="samelabs-table" style={{ marginTop: 24 }}>
        <thead>
          <tr>
            <th>client_id</th><th>名称</th><th>scope</th><th>额度(分/天)</th>
            <th>今日调用/错误</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.id}>
              <td className="mono">{row.client_id}</td>
              <td>{row.name}</td>
              <td>{row.scopes.join(", ")}</td>
              <td>{row.rate_per_minute} / {row.rate_per_day}</td>
              <td>{row.calls_today ?? 0} / {row.errors_today ?? 0}</td>
              <td>{row.enabled ? "启用" : "停用"}</td>
              <td>
                <Button variant="ghost" size="sm" disabled={busy}
                        onClick={() => void patch(row, { enabled: !row.enabled })}>
                  {row.enabled ? "停用" : "启用"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </section>;
}
