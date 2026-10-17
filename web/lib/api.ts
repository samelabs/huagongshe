/** 客户端取数走同源 BFF（app/api/[...path]）。服务端取数（page/layout/
 *  route handler）一律用 lib/api.server.ts —— 那一层带访客身份直连后端；
 *  本文件的服务端 base 已移除，服务端误用会在运行时立刻失败并被
 *  scripts/checkApiLayer.mjs 在提交前拦下。 */
const BASE = "/api";

/** BX-A2：用户创建且未填来源引用的反应，dataset_name 返回此稳定枚举标记
 *  （后端不再返回中文「用户发布」）—— 前端按语言渲染（t.reaction.userSubmitted）。 */
export const USER_SUBMITTED_SOURCE = "user_submitted";

export class ApiError extends Error {
  /** 服务端 error detail(如 FastAPI {"detail": "..."}), 可能为空 */
  detail?: string;
  /** v1.7.0 L2: 结构化 detail 的稳定机器码(如 Notes 引用校验 kind), 可能为空 */
  detailKind?: string;
  /** 字段级校验错误携带的字段名(invalid_field), 可能为空 */
  detailField?: string;
  constructor(public status: number, path: string, detail?: unknown) {
    super(`API ${status}: ${path}`);
    this.name = "ApiError";
    if (typeof detail === "string" && detail) this.detail = detail;
    else if (detail && typeof detail === "object" && "detail" in (detail as Record<string, unknown>)) {
      const inner = (detail as { detail: unknown }).detail;
      if (typeof inner === "string" && inner) this.detail = inner;
      // v1.7.0 L2: Notes 400 detail = {message, kind} — message 回填 detail,
      // kind 单独透出供五语言分类; 其他对象形态不受影响。
      else if (inner && typeof inner === "object") {
        const { message, kind, field } = inner as { message?: unknown; kind?: unknown; field?: unknown };
        if (typeof message === "string" && message) this.detail = message;
        if (typeof kind === "string" && kind) this.detailKind = kind;
        if (typeof field === "string" && field) this.detailField = field;
      }
    } else if (detail && typeof detail === "object") {
      const { message, kind, field } = detail as { message?: unknown; kind?: unknown; field?: unknown };
      if (typeof message === "string" && message) this.detail = message;
      if (typeof kind === "string" && kind) this.detailKind = kind;
      if (typeof field === "string" && field) this.detailField = field;
    }

    // 过渡兼容：后端未全部返回 {message, kind} 结构前，从已知中文 detail 映射出稳定 kind
    if (!this.detailKind && this.detail) {
      if (typeof this.detail === "string" && /^[a-z0-9_]+$/.test(this.detail)) {
        this.detailKind = this.detail;
      } else if (this.detail.includes("CAS") || this.detail === "invalid_cas") {
        this.detailKind = "invalid_cas";
      } else if (this.detail.includes("SMILES") || this.detail === "invalid_structure") {
        this.detailKind = "invalid_structure";
      } else if (this.detail.includes("至少") || this.detail === "query_too_short") {
        this.detailKind = "query_too_short";
      } else if (this.detail.includes("超时") || this.detail === "backend_unavailable") {
        this.detailKind = "backend_unavailable";
      } else if (this.detail.includes("substructure_too_small")) {
        this.detailKind = "substructure_too_small";
      } else if (this.detail.includes("invalid_doi")) {
        this.detailKind = "invalid_doi";
      }
    }
  }
}

/**
 * 统一报错文案函数（v1.7.1）：
 * 先按 detailKind 查字典 t.errors[kind]，查不到再用该场景的通用文案（fallback）。
 * 任何地方都不得直接渲染 err.detail。
 */
export function apiErrorMessage(
  error: unknown,
  t: { errors: Record<string, string> },
  fallback: string,
): string {
  if (error instanceof ApiError && error.detailKind) {
    const message = t.errors[error.detailKind];
    if (message) return message;
  }
  return fallback;
}


export function isApiNotFound(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404;
}

/** FX-3（SMK-002）：记录不存在的错误形态 —— 404（无此记录）与 422（ID 非法，
 *  FastAPI int-Path 校验拒绝）都应落到前端 404 页，而不是 500。 */
export function isApiGone(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.status === 404 || error.status === 422);
}

/** 实体详情 [id] 段的合法性：纯数字且 ≤ int32 上限（后端 Path le=2^31-1；
 * 超大数后端某些端点直接 500 而非 422，前端一律按非法 ID 处理）。不满足时
 * 调用方直接 notFound()，不把非法 ID 打到后端。 */
export function isEntityId(id: string): boolean {
  return /^\d+$/.test(id) && Number(id) <= 2_147_483_647;
}

async function safeDetail(response: Response): Promise<unknown> {
  try {
    return await response.clone().json();
  } catch {
    return undefined;
  }
}

// SSR服务端数据缓存层（A档）：仅用于低频、无用户态的读（如 /config）。
// 失效语义：revalidate 秒数内允许过期；admin 改 system_config 后最迟 revalidate 秒生效。
// 带 headers（cookie等用户态）的请求禁缓存，误用即抛错，不静默降级。
export async function apiGet<T>(path: string, headers?: HeadersInit, opts?: { revalidate?: number }): Promise<T> {
  if (opts?.revalidate != null && headers) {
    throw new Error(`apiGet: refusing cached request with headers (${path})`);
  }
  const response = await fetch(`${BASE}${path}`, {
    headers,
    ...(opts?.revalidate != null
      ? { next: { revalidate: opts.revalidate } }
      : { cache: "no-store" }),
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body instanceof FormData ? headers : { "Content-Type": "application/json", ...headers },
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiPatch<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: body instanceof FormData ? headers : { "Content-Type": "application/json", ...headers },
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiDelete<T>(path: string, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "DELETE",
    headers,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiPut<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: body instanceof FormData ? headers : { "Content-Type": "application/json", ...headers },
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

/** 化合物结构图（矢量）：地址不带尺寸，显示尺寸由页面 CSS 决定。 */
export function molSvgUrl(chemicalId: number): string {
  return `/img/chemical/${chemicalId}.svg`;
}

/** 反应方程式图（矢量）：地址不带尺寸，显示尺寸由页面 CSS 决定。 */
export function reactionSvgUrl(reactionId: number): string {
  return `/img/reaction/${reactionId}.svg`;
}

export type Chemical = {
  id: number;
  pubchem_cid: number | null;
  smiles: string | null;
  pubchem_smiles: string | null;
  preferred_name: string | null;
  iupac_name: string | null;
  /** locale 名称(name_index kind='name_cn', 镜像 CB identity.cn)。见 lib/chemicalName.ts */
  name_cn: string | null;
  molecular_formula: string | null;
  average_mass: number | null;
  monoisotopic_mass: number | null;
  inchikey: string | null;
  dtxsid: string | null;
  cas_numbers: string[];
  nikkaji_numbers: string[];
  chembl_ids: string[];
  ec_numbers: string[];
  unii_codes: string[];
  chebi_ids: string[];
  synonyms?: string[];
  synonym_count?: number;
  similarity: number | null;
  reaction_count?: number;
  follower_count?: number;
  is_following?: boolean;
  details?: ChemicalDetails | null;
  enrichment?: EnrichmentState;
  role?: string;
  occurrence_count?: number;
  amount_value?: number | null;
  amount_unit?: string | null;
  equivalents?: number | null;
  concentration_value?: number | null;
  concentration_unit?: string | null;
  yield_percent?: number | null;
};

export type ChemicalDetails = SemanticDetail;

/** E9-B semantic detail — 一级语义 section, PB/CB 不是一级 namespace。 */
export type SemanticDetail = {
  description: { source: string; record_description?: string | null };
  names: {
    cb_identity: Record<string, string | number>;
    cb_aliases: { value: string; source: string }[];
  };
  properties: {
    pb_computed: Record<string, number> | null;
    pb_physical_properties?: EvidenceBlock | null;
    cb_experimental: { label: string | null; text: string | null; v?: number | null; unit?: string | null; source: string }[];
    cb_prose: ProseItem[];
  };
  safety: {
    pb_sections?: Record<string, EvidenceBlock> | null;
    cb_safety?: Record<string, string> | null;
    cb_toxicity: ProseItem[];
    cb_packaging: ProseItem[];
  };
  industry: {
    pb_sections?: Record<string, EvidenceBlock> | null;
    cb_uses: ProseItem[];
    cb_preparation: ProseItem[];
    cb_updown: { up: { name: string }[]; down: { name: string }[] };
    cb_price: { updated?: string; code: string; name?: string; cas?: string; package?: string; price?: string }[];
    cb_notes: ProseItem[];
  };
  suppliers: { items: CasSupplier[] };
  provenance: {
    pubchem: { state: string; fetched_at?: string | null; job_id?: number | null };
    cb: { state: string; applicable?: boolean };
  };
};

export type ProseItem = { title: string; text: string; source: string };

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

export type EvidenceBlock = {
  entries?: Record<string, unknown>;
  [key: string]: unknown;
};

export type EnrichmentState = {
  status: "current" | "queued" | "stale" | "degraded";
  sources?: { pubchem: string; cb: string };
  job_id?: number | null;
  requested_sections?: string[];
};

export type NoteVisibility = "all" | "public" | "private";

export type NoteItem = {
  id: number;
  owner_user_id: number;
  visibility: "public" | "private";
  moderation_status: "visible" | "hidden";
  content: string;
  created_at: string;
  updated_at: string;
  username: string;
  display_name: string | null;
  /* 与接口投影同口径的用户四字段; active=false 时渲染「已停用」 */
  avatar_url?: string | null;
  active?: boolean;
  chemical_ids: number[];
  reaction_ids: number[];
};

export type NoteResponse = {
  items: NoteItem[];
  total: number;
  page: number;
  page_size: number;
};

export type ReactionSummary = {
  id: number;
  reaction_smiles: string | null;
  doi: string | null;
  patent: string | null;
  dataset_name: string | null;
  matched_roles: string[];
};

export type ReactionLookup = {
  id: number;
  reaction_smiles: string | null;
  ord_id: string | null;
  dataset_name: string | null;
  doi: string | null;
  patent: string | null;
  match_basis: "reaction_id" | "ord_id" | "doi";
};

export type SearchResponse = {
  threshold?: number;
  query: string;
  mode: string;
  canonical_smiles: string | null;
  page: number;
  page_size: number;
  total: number | null;
  /** 权威翻页字段(Search System Governance): 能否继续翻页只认它 */
  has_more?: boolean;
  /** substructure snapshot 达到产品上限 250 时 true — total 不是数据库真实总数 */
  capped?: boolean;
  chemicals: Chemical[];
  reactions: ReactionLookup[];
  /** CAS 未命中且已入队自动获取时为 true（2026-08-27 起后端返回） */
  cas_fetch_pending?: boolean;
  /** 0902 P3b: 同步拉命中 — CB 数据已落库, 前端直接跳详情页 */
  cas_fetch_chemical_id?: number;
};

export type ReactionDetail = {
  id: number;
  reaction_smiles: string | null;
  ord_record_id: number | null;
  ord_id: string | null;
  dataset_name: string | null;
  doi: string | null;
  patent: string | null;
  publication_url: string | null;
  procedure_details: string | null;
  safety_notes: string | null;
  reflux: boolean | null;
  ph: number | null;
  conditions_detail: string | null;
  temperature: { value: number; unit: string } | null;
  duration: { value: number; unit: string } | null;
  atmosphere: string | null;
  pressure: { value: number; unit: string } | null;
  visibility: "public" | "private";
  moderation_status: "visible" | "hidden";
  created_at: string;
  updated_at: string;
  source_type: string | null;
  source_citation: string | null;
  workup_details: string | null;
  note: string | null;
  creator: { username: string; display_name: string; avatar_url: string | null; active?: boolean; is_following?: boolean } | null;
  is_owner: boolean;
  follower_count: number;
  is_following: boolean;
  participants: Chemical[];
  workup: { type: string | null; details: string | null; keep_phase: string | null; target_ph: number | null }[];
};

export type User = {
  id: number;
  username: string;
  display_name: string;
  email?: string;
  role?: "member" | "admin";
  avatar_url: string | null;
};
