"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPut, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type ConfigEntry = { namespace: string; key: string; value: Record<string, unknown> };

const FIELD_LABELS: Record<string, string> = {
  provider: t.admin.configProvider, id: "ID", enabled: t.admin.configEnabled,
  client: t.admin.configClient,
  public_base_url: t.admin.configBaseUrl, api_title: t.admin.configApiTitle,
  footer: t.admin.configFooter,
};

export function SamelabsConfig() {
  const [entries, setEntries] = useState<ConfigEntry[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [busyKey, setBusyKey] = useState("");

  useEffect(() => {
    let active = true;
    apiGet<ConfigEntry[]>(`/admin/config`).then((data) => {
      if (active) setEntries(data);
    }).catch((err) => {
      if (!active) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errConfigLoad);
    });
    return () => { active = false; };
  }, []);

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
      await apiPut(`/admin/config/${entry.namespace}/${entry.key}`, JSON.stringify(entry.value));
      // 只标记已保存: 本地 value 已是刚提交的值, 不做全量 reload
      // (全量 reload 会整体替换 entries, 覆盖其他 entry 未保存的 draft)
      setSaved(t.admin.saved(key));
    } catch {
      setError(t.admin.errSaveFailed);
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
            <option value="true">{t.admin.optionEnabled}</option>
            <option value="false">{t.admin.optionDisabled}</option>
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
        {error && <div className="notice error">{error}</div>}
        {saved && <div className="notice success">{saved}</div>}
        {renderSection("analytics", getByNs("analytics"))}
        {renderSection("ads", getByNs("ads"))}
        {renderSection("site", getByNs("site"))}
        {renderSection("branding", getByNs("branding"))}
  </>;
}
