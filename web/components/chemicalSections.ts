/**
 * CB externals 数据契约(自 CasExternals.tsx 迁入 —— 该组件已删除,
 * 页面不再渲染 source-first 大块, 类型是唯一被保留的部分)。
 */
export type CasIdentity = {
  cn?: string;
  en?: string;
  alias_cn?: string[];
  alias_en?: string[];
  formula?: string;
  mw?: number;
};

export type CasProp = {
  key: string;
  label: string;
  text: string;
  v?: number;
  unit?: string;
};

export type CasEntry = {
  identity?: CasIdentity;
  props?: CasProp[];
  safety?: Record<string, string>;
  price?: { updated: string; code: string; name: string; cas: string; package: string; price: string }[];
  updown?: { up?: { name: string; cb_number?: string }[]; down?: { name: string; cb_number?: string }[] };
  prose?: { title: string; text: string }[];
};

export type CasSupplier = {
  ref: string;
  name: string;
  phone: string | null;
  email: string | null;
  website: string | null;
  purity: string | null;
  pack_price: string | null;
  remark: string | null;
};

export type CasExternalsPayload = {
  chemical_id: number;
  state: string;
  entry: CasEntry | null;
  suppliers: CasSupplier[];
};

/**
 * Chemical semantic composition helpers (Design System v2, Issue #4)。
 *
 * 把 CB externals + PB details 从"source-first 渲染组件"重组为"semantic section 数据"。
 * 组件不再自己决定页面 IA —— page.tsx 拥有一级主题，这里只做数据分组。
 *
 * 硬约束(DESIGN_SYSTEM_V2 §6.4): 不为视觉整合发明数据合并 ——
 * CB 值与 PB 值各自保留原值与来源, 只进同一个语义 section。
 */

export type SemanticProperty = { label: string; value: string };

export type SemanticProse = { title: string; text: string };

/** Properties section 输入。 */
export function propertyGroups(payload: CasExternalsPayload | null): {
  cbExperimental: SemanticProperty[];
  cbChemicalProse: SemanticProse[];
} {
  const props = ((payload?.entry?.props ?? []).filter((p): p is CasProp =>
    !!p && typeof p === "object" && typeof (p as CasProp).key === "string" && typeof (p as CasProp).text === "string"));
  return {
    cbExperimental: props.map((p) => ({
      label: p.label,
      value: p.v != null ? `${p.v}${p.unit ? ` ${p.unit}` : ""} · ${p.text}` : p.text,
    })),
    cbChemicalProse: proseOf(payload).filter((i) => proseGroup(i.title) === "properties"),
  };
}

/** Safety & Regulatory section 输入。 */
export function safetyGroups(payload: CasExternalsPayload | null): {
  cbSafety: SemanticProperty[];
  cbToxicity: SemanticProse[];
  cbPackaging: SemanticProse[];
} {
  const raw = payload?.entry?.safety;
  const safety = raw && !Array.isArray(raw) ? Object.entries(raw) : [];
  return {
    cbSafety: safety.map(([k, v]) => ({ label: k, value: v })),
    cbToxicity: proseOf(payload).filter((i) => proseGroup(i.title) === "toxicity"),
    cbPackaging: proseOf(payload).filter((i) => proseGroup(i.title) === "packaging"),
  };
}

/** Chemistry & Industry section 输入。 */
export function industryGroups(payload: CasExternalsPayload | null): {
  uses: SemanticProse[];
  preparation: SemanticProse[];
  updown: { direction: "up" | "down"; name: string }[];
  price: { label: string; value: string }[];
  suppliers: CasSupplier[];
  notes: SemanticProse[];
} {
  const entry = payload?.entry;
  const isNamed = (n: unknown): n is { name: string; cb_number?: string } =>
    !!n && typeof n === "object" && typeof (n as { name: string }).name === "string";
  const isPriceRow = (r: unknown): r is { updated: string; code: string; name: string; cas: string; package: string; price: string } =>
    !!r && typeof r === "object" && typeof (r as { code: string }).code === "string";
  return {
    uses: proseOf(payload).filter((i) => proseGroup(i.title) === "uses"),
    preparation: proseOf(payload).filter((i) => proseGroup(i.title) === "preparation"),
    updown: [
      ...(entry?.updown?.up ?? []).filter(isNamed).map((n) => ({ direction: "up" as const, name: n.name })),
      ...(entry?.updown?.down ?? []).filter(isNamed).map((n) => ({ direction: "down" as const, name: n.name })),
    ],
    price: (entry?.price ?? []).filter(isPriceRow).map((r) => ({ label: `${r.code} · ${r.package}`, value: `${r.name} — ${r.price}` })),
    suppliers: payload?.suppliers ?? [],
    notes: proseOf(payload).filter((i) => proseGroup(i.title) === "notes"),
  };
}

/** Names & Identifiers: CB 名称子块(中文名/英文名/formula/mw)与别名。 */
export function cbNameGroups(payload: CasExternalsPayload | null, canonical: string[] = []): {
  identity: { label: string; value: string }[];
  aliases: string[];
} {
  const identity = payload?.entry?.identity &&
    typeof payload.entry.identity === "object" && !Array.isArray(payload.entry.identity)
    ? payload.entry.identity : undefined;
  const out: { label: string; value: string }[] = [];
  // 同一字符串只在 Names 区出现一次: CB 英文名与 canonical 名逐字相同时不重复列出
  const canon = new Set(canonical.filter(Boolean).map((v) => v.trim().toLowerCase()));
  if (identity?.cn && !canon.has(identity.cn.trim().toLowerCase())) out.push({ label: "中文名", value: identity.cn });
  if (identity?.en && !canon.has(identity.en.trim().toLowerCase())) out.push({ label: "英文名", value: identity.en });
  if (identity?.formula) out.push({ label: "分子式", value: identity.formula });
  if (identity?.mw != null) out.push({ label: "分子量", value: String(identity.mw) });
  const aliases = [...(identity?.alias_cn ?? []), ...(identity?.alias_en ?? [])].filter(Boolean);
  return { identity: out, aliases };
}

/* ── 内部: prose 读取与语义分组(白名单与 0905 解析层同源) ── */

const PROSE_GROUPS: [RegExp, string][] = [
  [/^(用途|应用|概述|简介|主要应用)$/, "uses"],
  [/^(生产方法|制备)$/, "preparation"],
  [/^(化学性质|性状)$/, "properties"],
  [/^(毒性|毒性分级|急性毒性|刺激数据|职业标准)$/, "toxicity"],
  [/^(储运特性|可燃性危险特性|爆炸物危险特性|灭火剂|类别)$/, "packaging"],
];

function proseGroup(title: string): string {
  for (const [pat, group] of PROSE_GROUPS) {
    if (pat.test(title)) return group;
  }
  return "notes";
}

function proseOf(payload: CasExternalsPayload | null): SemanticProse[] {
  const raw = payload?.entry?.prose ?? [];
  return raw.filter((i): i is { title: string; text: string } =>
    !!i && typeof i === "object" && typeof (i as { title: string }).title === "string" && typeof (i as { text: string }).text === "string");
}
