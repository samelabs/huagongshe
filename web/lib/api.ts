const SERVER_API = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api";
const CLIENT_API = "/api";
const BASE = typeof window !== "undefined" ? CLIENT_API : SERVER_API;

export class ApiError extends Error {
  constructor(public status: number, path: string) {
    super(`API ${status}: ${path}`);
    this.name = "ApiError";
  }
}

export function isApiNotFound(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404;
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
  if (!response.ok) throw new ApiError(response.status, path);
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body instanceof FormData ? headers : { "Content-Type": "application/json", ...headers },
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path);
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiPatch<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: body instanceof FormData ? headers : { "Content-Type": "application/json", ...headers },
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path);
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiDelete<T>(path: string, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "DELETE",
    headers,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path);
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiPut<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: body instanceof FormData ? headers : { "Content-Type": "application/json", ...headers },
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path);
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export function molSvgUrl(chemicalId: number, width = 260, height = 180) {
  return `/api/mol/${chemicalId}/svg/${width}x${height}.svg`;
}

export function reactionSvgUrl(reactionId: number, width = 1100, height = 230) {
  return `/api/reactions/${reactionId}/svg/${width}x${height}.svg`;
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

export type ChemicalDetails = {
  record_title?: string | null;
  record_description?: string | null;
  xlogp?: number | null;
  topological_polar_surface_area?: number | null;
  complexity?: number | null;
  hbond_donor_count?: number | null;
  hbond_acceptor_count?: number | null;
  rotatable_bond_count?: number | null;
  heavy_atom_count?: number | null;
  formal_charge?: number | null;
  physical_properties?: EvidenceBlock | null;
  ghs_classification?: EvidenceBlock | null;
  hazards?: EvidenceBlock | null;
  safety_measures?: EvidenceBlock | null;
  toxicity?: EvidenceBlock | null;
  regulatory?: EvidenceBlock | null;
  pharmacology?: EvidenceBlock | null;
  uses_and_manufacturing?: EvidenceBlock | null;
  fetched_at?: string | null;
};

export type EvidenceBlock = {
  entries?: Record<string, unknown>;
  [key: string]: unknown;
};

export type EnrichmentState = {
  status: "queued" | "stale" | "current";
  job_id?: number | null;
  requested_sections?: string[];
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
  creator: { username: string; display_name: string; avatar_url: string | null } | null;
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
