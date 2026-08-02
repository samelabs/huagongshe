const SERVER_API = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api";

export class ApiError extends Error {
  constructor(public status: number, path: string) {
    super(`API ${status}: ${path}`);
    this.name = "ApiError";
  }
}

export function isApiNotFound(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404;
}

export async function apiGet<T>(path: string, revalidate = 0, headers?: HeadersInit): Promise<T> {
  const response = await fetch(`${SERVER_API}${path}`, {
    headers,
    next: revalidate > 0 ? { revalidate } : undefined,
    cache: revalidate > 0 ? "force-cache" : "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path);
  return response.json() as Promise<T>;
}

export function molSvgUrl(smiles: string, width = 260, height = 180) {
  return `/api/mol/svg?smiles=${encodeURIComponent(smiles)}&w=${width}&h=${height}`;
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
  fetched_sections?: string[];
  section_fetched_at?: Record<string, string>;
  fetched_at?: string | null;
};

export type EvidenceBlock = {
  entries?: Record<string, unknown>;
  [key: string]: unknown;
};

export type EnrichmentState = {
  status: "queued" | "rate_limited" | "current";
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
  query: string;
  mode: string;
  canonical_smiles: string | null;
  chemicals: Chemical[];
  reactions: ReactionLookup[];
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
