import type { EvidenceBlock } from "@/lib/api";

/**
 * PubChem evidence 语义块 (Design System v2, Issue #4)。
 * 从 ChemicalKnowledge 的"8 个 source-first H2 section"改为语义 section 的子块数据:
 * - physical_properties → Properties/Experimental
 * - ghs/hazards/safety_measures/toxicity/regulatory → Safety & Regulatory
 * - pharmacology/uses_and_manufacturing → Chemistry & Industry
 *
 * disclosure 新规(替代旧 index<3 默认开): 高价值摘要直接可见, 长列表默认折叠。
 * 不删数据 — 只改默认展开。
 */

export type EvidenceEntry = { label: string; values: string[] };

function evidenceEntries(block: EvidenceBlock | null | undefined): EvidenceEntry[] {
  if (!hasEntries(block)) return [];
  const source = block!.entries && typeof block!.entries === "object" ? block!.entries : block!;
  return Object.entries(source)
    .filter(([key]) => !["references", "normalization"].includes(key))
    .map(([path, values]) => ({ label: leafLabel(path), values: displayValues(values) }))
    .filter((e) => e.values.length > 0);
}

/** 短列表(≤2 值且每值 ≤160 字)视为摘要直接可见; 长列表默认折叠。 */
export function isSummary(entry: EvidenceEntry): boolean {
  return entry.values.length <= 2 && entry.values.every((v) => v.length <= 160);
}

export function evidenceSectionKeys(details: Record<string, unknown>): Record<string, EvidenceEntry[]> {
  const keys = ["physical_properties", "ghs_classification", "hazards", "safety_measures", "toxicity", "regulatory", "pharmacology", "uses_and_manufacturing"];
  const out: Record<string, EvidenceEntry[]> = {};
  for (const key of keys) {
    const entries = evidenceEntries(details[key] as EvidenceBlock | undefined);
    if (entries.length) out[key] = entries;
  }
  return out;
}

/* ── 以下与旧 ChemicalKnowledge 渲染逻辑同源(数据保真, 不改解析) ── */

function hasEntries(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  const entries = record.entries && typeof record.entries === "object" ? record.entries as Record<string, unknown> : record;
  return Object.keys(entries).some((key) => !["references", "normalization"].includes(key));
}

function leafLabel(path: string) {
  return path.split(" > ").at(-1) || path;
}

function displayValues(input: unknown): string[] {
  const list = Array.isArray(input) ? input : [input];
  const result: string[] = [];
  for (const item of list) {
    if (item == null) continue;
    if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
      result.push(String(item)); continue;
    }
    if (typeof item === "object") {
      const record = item as Record<string, unknown>;
      const raw = record.value ?? record.name ?? record.description ?? record.text;
      if (Array.isArray(raw)) result.push(raw.map((value) => scalar(value)).filter(Boolean).join("；"));
      else if (raw != null) result.push(scalar(raw));
    }
  }
  return result.filter(Boolean);
}

function scalar(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.StringWithMarkup && Array.isArray(record.StringWithMarkup)) {
      return record.StringWithMarkup.map((item) => scalar((item as Record<string, unknown>)?.String)).filter(Boolean).join(" ");
    }
  }
  return "";
}
