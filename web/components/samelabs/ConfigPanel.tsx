"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPut, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type ConfigEntry = { namespace: string; key: string; value: Record<string, unknown> };

/**
 * 渲染白名单 — 与后端 CONFIG_SCHEMA(admin.py) 对齐的已知可管理字段。
 * 未列出的字段一律只读展示(不自动生成可编辑控件), 防止未知对象被误写入。
 */
type FieldSpec = { field: string; label: string; type: "text" | "boolean" };

const RENDERABLE: Record<string, FieldSpec[]> = {
  "analytics/scripts": [
    { field: "provider", label: t.admin.configProvider, type: "text" },
    { field: "id", label: "ID", type: "text" },
    { field: "enabled", label: t.admin.configEnabled, type: "boolean" },
  ],
  "ads/adsense": [
    { field: "enabled", label: t.admin.configEnabled, type: "boolean" },
    { field: "client", label: t.admin.configClient, type: "text" },
  ],
  "site/meta": [
    { field: "public_base_url", label: t.admin.configBaseUrl, type: "text" },
    { field: "api_title", label: t.admin.configApiTitle, type: "text" },
  ],
  "branding/slogan": [
    { field: "footer", label: t.admin.configFooter, type: "text" },
  ],
};

const SECRET_HINT = /(secret|token|password|api[_-]?key|private)/i;

function isSensitive(field: string): boolean {
  return SECRET_HINT.test(field);
}

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

  function renderField(entry: ConfigEntry, spec: FieldSpec) {
    const value = entry.value[spec.field];
    const disabled = isSensitive(spec.field);
    const label = spec.label;
    if (spec.type === "boolean") {
      return <label key={spec.field}>{label}
        <select value={value ? "true" : "false"} onChange={(e) => updateValue(entry.namespace, entry.key, spec.field, e.target.value === "true")}>
          <option value="true">{t.admin.optionEnabled}</option>
          <option value="false">{t.admin.optionDisabled}</option>
        </select>
      </label>;
    }
    return <label key={spec.field}>{label}
      <input
        value={disabled ? "" : String(value || "")}
        placeholder={disabled ? "已隐藏" : ""}
        disabled={disabled}
        title={disabled ? "敏感配置不在页面展示" : undefined}
        onChange={(e) => updateValue(entry.namespace, entry.key, spec.field, e.target.value)} />
    </label>;
  }

  function renderSection(title: string, sectionEntries: ConfigEntry[]) {
    if (sectionEntries.length === 0) return null;
    return <section key={title} className="form-section">
      <div className="form-section-head"><span>{title.toUpperCase()}</span><div><h2>{title}</h2></div></div>
      {sectionEntries.map((entry) => {
        const key = `${entry.namespace}/${entry.key}`;
        const specs = RENDERABLE[key] ?? [];
        return <div key={key} className="form-fields">
          {specs.map((spec) => renderField(entry, spec))}
          <button type="button" className="button primary small" disabled={busyKey === key} onClick={() => save(entry)}>
            {busyKey === key ? t.admin.saving : t.admin.save}
          </button>
        </div>;
      })}
    </section>;
  }

  return <>
    <header className="page-title">
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
