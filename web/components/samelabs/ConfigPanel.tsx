"use client";

import { useEffect, useState } from "react";
import { SamelabsNav } from "@/components/SamelabsNav";
import t from "@/lib/i18n";

type ConfigEntry = { namespace: string; key: string; value: Record<string, unknown> };

const FIELD_LABELS: Record<string, string> = {
  provider: "服务商", id: "ID", enabled: "状态",
  client: "客户号",
  public_base_url: "站点 URL", api_title: "API 标题",
  footer: "底部文案",
};

export function SamelabsConfig() {
  const [entries, setEntries] = useState<ConfigEntry[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [busyKey, setBusyKey] = useState("");

  async function load() {
    setError("");
    const res = await fetch("/api/admin/config", { cache: "no-store" });
    if (res.status === 401 || res.status === 403) { setError(t.admin.noPermission); return; }
    if (!res.ok) { setError(t.admin.errConfigLoad); return; }
    setEntries(await res.json());
  }

  useEffect(() => { load(); }, []);

  function updateValue(ns: string, key: string, field: string, value: string | boolean) {
    setEntries((prev) => prev.map((e) =>
      e.namespace === ns && e.key === key
        ? { ...e, value: { ...e.value, [field]: value } }
        : e
    ));
  }

  async function save(entry: ConfigEntry) {
    const key = `${entry.namespace}/${entry.key}`;
    setBusyKey(key); setSaved("");
    try {
      const res = await fetch(`/api/admin/config/${entry.namespace}/${entry.key}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry.value),
      });
      if (!res.ok) { setError(t.admin.errSaveFailed); return; }
      setSaved(t.admin.saved(key));
      await load();
    } catch {
      setError(t.admin.errNetwork);
    } finally {
      setBusyKey("");
    }
  }

  if (error && entries.length === 0) return <div className="notice error">{error}</div>;

  const getByNs = (ns: string) => entries.filter((e) => e.namespace === ns);

  function renderField(entry: ConfigEntry, field: string, type: "text" | "boolean" = "text") {
    const value = entry.value[field];
    const label = FIELD_LABELS[field] || field;
    return <label key={field}>{label}
      {type === "boolean"
        ? <select value={value ? "true" : "false"} onChange={(e) => updateValue(entry.namespace, entry.key, field, e.target.value === "true")}>
            <option value="true">启用</option>
            <option value="false">停用</option>
          </select>
        : <input value={String(value || "")} onChange={(e) => updateValue(entry.namespace, entry.key, field, e.target.value)} />
      }
    </label>;
  }

  function renderSection(title: string, entries: ConfigEntry[]) {
    if (entries.length === 0) return null;
    return <section key={title} className="form-section">
      <div className="form-section-head"><span>{title.toUpperCase()}</span><div><h2>{title}</h2></div></div>
      {entries.map((entry) => {
        const key = `${entry.namespace}/${entry.key}`;
        const fields = Object.keys(entry.value);
        return <div key={key} className="form-fields">
          {fields.map((field) => renderField(entry, field, typeof entry.value[field] === "boolean" ? "boolean" : "text"))}
          <button type="button" className="button primary small" disabled={busyKey === key} onClick={() => save(entry)}>
            {busyKey === key ? t.admin.saving : t.admin.save}
          </button>
        </div>;
      })}
    </section>;
  }

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.configKicker}</p>
      <h1>{t.admin.configTitle}</h1>
    </header>
    <div className="settings-layout">
      <SamelabsNav />
      <div className="settings-content">
        {error && <div className="notice error">{error}</div>}
        {saved && <div className="notice success">{saved}</div>}
        {renderSection("analytics", getByNs("analytics"))}
        {renderSection("ads", getByNs("ads"))}
        {renderSection("site", getByNs("site"))}
        {renderSection("branding", getByNs("branding"))}
      </div>
    </div>
  </>;
}
