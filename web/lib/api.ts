const SERVER_API = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api";

export async function apiGet<T>(path: string, revalidate = 0): Promise<T> {
  const response = await fetch(`${SERVER_API}${path}`, {
    next: revalidate > 0 ? { revalidate } : undefined,
    cache: revalidate > 0 ? "force-cache" : "no-store",
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json() as Promise<T>;
}

export function molSvgUrl(smiles: string, width = 260, height = 180) {
  return `/api/mol/svg?smiles=${encodeURIComponent(smiles)}&w=${width}&h=${height}`;
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
  role?: string;
  yield_percent?: number | null;
};

export type ReactionSummary = {
  id: number;
  reaction_smiles: string | null;
  doi: string | null;
  patent: string | null;
  dataset_name: string | null;
  matched_role: string | null;
};

export type SearchResponse = {
  query: string;
  mode: string;
  canonical_smiles: string | null;
  chemicals: Chemical[];
};

export type ReactionDetail = {
  id: number;
  reaction_smiles: string;
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
  community_submission_id: number | null;
  participants: Chemical[];
  workup: { type: string | null; details: string | null; keep_phase: string | null; target_ph: number | null }[];
};
