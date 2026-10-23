import type { Metadata } from "next";
import Link from "next/link";
import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";

// 内部文档：只在后台（/samelabs 布局鉴权、noindex）提供，由管理员随凭证交给对接方。
export const metadata: Metadata = {
  title: "Data service API",
};

type FieldRow = { name: string; type: string; desc: string };

function FieldTable({ rows }: { rows: FieldRow[] }) {
  return (
    <div className="hg-code multiline" style={{ overflowX: "auto" }}>
      <table className="token-table">
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <th>{row.name}</th>
              <td>
                <code className="token-code">{row.type}</code>
                <span style={{ display: "block", marginTop: 2 }}>{row.desc}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const chemicalHeader: FieldRow[] = [
  { name: "hcid", type: "integer", desc: "Huagongshe Chemical ID." },
  { name: "title", type: "string", desc: "Display name, same rule as the compound page (local common name, English fallback)." },
  { name: "subtitle", type: "string|null", desc: "English common name when the title is a local name." },
  { name: "cas", type: "string|null", desc: "First CAS registry number." },
  { name: "formula", type: "string|null", desc: "Molecular formula." },
  { name: "molecular_weight", type: "number|null", desc: "Average molecular weight, g/mol." },
  { name: "structure_image", type: "string", desc: "Structure depiction PNG (800×800)." },
  { name: "data_status", type: "complete|updating", desc: "Whether enrichment is settled or still being fetched." },
  { name: "data_updated_at", type: "string|null", desc: "Last enrichment fetch time." },
];

const chemicalOverview: FieldRow[] = [
  { name: "overview.description", type: "string|null", desc: "Summary text, complete." },
  { name: "overview.smiles", type: "string|null", desc: "Canonical SMILES." },
  { name: "overview.inchikey", type: "string|null", desc: "InChIKey." },
  { name: "overview.iupac_name", type: "string|null", desc: "IUPAC name." },
  { name: "overview.exact_mass", type: "number|null", desc: "Monoisotopic mass, g/mol." },
];

const chemicalNames: FieldRow[] = [
  { name: "names.local_name", type: "string|null", desc: "Common name in the requested locale." },
  { name: "names.english_name", type: "string|null", desc: "English common name." },
  { name: "names.synonyms", type: "string[]", desc: "Synonyms as shown on the page (capped), every language equally." },
  { name: "names.synonyms_total", type: "integer", desc: "Total synonym count before the display cap." },
  { name: "names.identifiers", type: "object", desc: "pubchem_cid, cas_numbers, dtxsid, ec_numbers, chebi_ids, chembl_ids, unii_codes, nikkaji_numbers." },
];

const chemicalPartitions: FieldRow[] = [
  { name: "properties", type: "field[]", desc: "Physical and chemical properties. Each field: label, values[], optional unit. Same merge rule as the page — each field appears once." },
  { name: "safety.ghs", type: "field[]", desc: "GHS classification fields." },
  { name: "safety.hazards", type: "field[]", desc: "Hazard fields." },
  { name: "safety.safety_measures", type: "field[]", desc: "Storage, protection, packaging and transport fields." },
  { name: "safety.toxicity", type: "field[]", desc: "Toxicity fields." },
  { name: "safety.regulatory", type: "field[]", desc: "Regulatory inventory fields (TSCA, water hazard class, customs and similar)." },
  { name: "industry.uses", type: "{title,text}[]", desc: "Applications, complete text." },
  { name: "industry.preparation", type: "{title,text}[]", desc: "Preparation routes, complete text." },
  { name: "industry.upstream / industry.downstream", type: "string[]", desc: "Upstream and downstream product names." },
  { name: "industry.prices", type: "{name,package,price,updated}[]", desc: "Reference reagent prices." },
  { name: "suppliers", type: "{name,phone,email}[]", desc: "Supplier directory entries." },
];

const reactionFields: FieldRow[] = [
  { name: "hrid", type: "integer", desc: "Huagongshe Reaction ID. Only public reactions are returned." },
  { name: "title", type: "string", desc: "Primary reactant → primary product, same selection rule as the reaction page." },
  { name: "equation_image", type: "string", desc: "Reaction equation SVG." },
  { name: "equation_smiles", type: "string", desc: "Reaction SMILES." },
  { name: "participants", type: "object[]", desc: "role (REACTANT/REAGENT/CATALYST/SOLVENT/PRODUCT), name, hcid, occurrence_count, amount {value, unit, equivalents}, yield_percent." },
  { name: "conditions", type: "object", desc: "temperature, duration, pressure, atmosphere, ph, reflux, details — values only when reported." },
  { name: "procedure", type: "string|null", desc: "Procedure text, complete." },
  { name: "workup / note / safety_notes", type: "string|null", desc: "Workup, note and safety text, complete." },
  { name: "references", type: "object", desc: "source_type, doi, patent, url, citation." },
];

const errorCodes: FieldRow[] = [
  { name: "unauthorized", type: "401", desc: "Missing or invalid credential, bad signature, or timestamp outside ±300 s." },
  { name: "replayed_request", type: "401", desc: "Nonce already used inside the replay window." },
  { name: "forbidden_scope", type: "403", desc: "The credential does not cover this method and path." },
  { name: "not_found", type: "404", desc: "Unknown, merged or invisible record." },
  { name: "invalid_parameter", type: "422", desc: "Malformed or out-of-range parameter." },
  { name: "rate_limited", type: "429", desc: "Credential quota exceeded; Retry-After header included." },
  { name: "unavailable", type: "503", desc: "Service temporarily unavailable." },
];

const signExample = `import hashlib, hmac, time, uuid, urllib.request

BASE = "https://huagongshe.com"
CLIENT_ID = "hgsd-0123456789abcdef"
TOKEN = "hgsd_..."   # issued once, keep it secret

def call(path, query=""):
    method = "GET"
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    body_hash = hashlib.sha256(b"").hexdigest()   # empty body for GET
    message = "\\n".join([method, path, query, body_hash, timestamp, nonce])
    signature = hmac.new(TOKEN.encode(), message.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "X-Client-Id": CLIENT_ID,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode()

print(call("/data/v1/chemicals/996", query="locale=zh-CN"))`;

export default function DataApiDocsPage() {
  return (
    <>
      {/* 文档主体走阅读档；字段/端点表列宽超阅读档，各自放 page 档页框
          （组件 tier 组合表达宽表突破，不写页面私有样式） */}
      <PageFrame tier="content" className="data-api-page">
        <PageHead
          title="Data service API"
          subtitle={<>Huagongshe issues credentials to authorized systems for on-demand compound
          and reaction queries. All endpoints are read-only GET. Responses are JSON,
          carry a <code className="token-code">request_id</code>, and follow the same
          partitions and fields as the corresponding pages — a field appears once,
          independent of how many sources contributed to it. Results are reference
          data and do not replace scientific, safety, regulatory or process review.</>}
        />
      </PageFrame>

      <PageFrame tier="page" className="data-api-page">
        <Section title="Endpoints">
          <FieldTable rows={[
            { name: "GET /data/v1/chemicals/{hcid}?locale=", type: "object", desc: "One compound, full projection. locale: zh-CN, en, ja, ko or de; missing fields fall back to English." },
            { name: "GET /data/v1/chemicals?ids=1,2,3&locale=", type: "object", desc: "Batch of compounds, at most 50 ids. Unknown ids are listed under missing." },
            { name: "GET /data/v1/chemicals/lookup?hcid=|cas=|smiles=|inchikey=|name=&locale=", type: "object", desc: "Candidate list (hcid, title, match), at most 20. Exactly one selector per call. Name lookup tries exact match first, then substring once the normalized name is at least 3 characters; every language participates equally. Unknown SMILES create a record and start collection (returns the new HCID with data_status updating); unknown CAS enter the collection queue (check back for the HCID). Substructure and similarity search are not part of this service." },
            { name: "GET /data/v1/reactions/{hrid}?locale=", type: "object", desc: "One public reaction, full projection." },
            { name: "GET /data/v1/reactions?ids=...", type: "object", desc: "Batch of public reactions, at most 20 ids." },
            { name: "GET /data/v1/chemicals/{hcid}/reactions?page=&page_size=", type: "object", desc: "Public reaction summaries involving the compound; page_size at most 50." },
          ]} />
        </Section>
      </PageFrame>

      <PageFrame tier="content" className="data-api-page">
        <Section title="Scopes">
          <p className="doc-prose">
            <code className="token-code">data:chemical:read</code> covers the four
            chemical endpoints; <code className="token-code">data:reaction:read</code>{" "}
            covers the two reaction endpoints. Scopes map to exact (method, path)
            pairs — anything not registered is refused with{" "}
            <code className="token-code">forbidden_scope</code>.
          </p>
        </Section>

        <Section title="Request signing">
          <p className="doc-prose">
            Every request carries five headers. The signature is hex HMAC-SHA256
            keyed with the token over the newline-joined request elements, in order:
            method, path (without query), raw query string (empty when none),
            hex SHA-256 of the body (hex SHA-256 of the empty string for GET),
            timestamp, nonce. The timestamp may deviate at most ±300 seconds from
            server time; a nonce is accepted once per credential inside the replay
            window.
          </p>
          <div className="hg-code multiline" style={{ overflowX: "auto" }}>
            <pre className="document-text" style={{ whiteSpace: "pre" }}>{signExample}</pre>
          </div>
        </Section>
      </PageFrame>

      <PageFrame tier="page" className="data-api-page">
        <Section title="Compound fields">
          <FieldTable rows={[...chemicalHeader, ...chemicalOverview, ...chemicalNames, ...chemicalPartitions]} />
        </Section>

        <Section title="Reaction fields">
          <FieldTable rows={reactionFields} />
        </Section>

        <Section title="Errors and limits">
          <p className="doc-prose">
            Errors use <code className="token-code">{"{\"error\": {\"code\", \"message\"}}"}</code>{" "}
            plus <code className="token-code">request_id</code>. Within a version
            fields are only added, never changed or removed. Quotas are per
            credential (per minute and per day); exceeding them returns 429 with a
            Retry-After header.
          </p>
          <FieldTable rows={errorCodes} />
          <p className="doc-prose">
            To request a credential, contact the operators of Huagongshe. Records
            fetched by this service should be stored by the calling system; the
            service does not push updates.
          </p>
          <p>
            <Link href="/samelabs/data-clients" className="TextLink">Back to data service credentials</Link>
          </p>
        </Section>
      </PageFrame>
    </>
  );
}
