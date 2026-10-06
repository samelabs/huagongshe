# HGS v1.7.0 OpenAI Plugin submission readiness

Status: pre-deployment execution artifact

## Frozen product boundary

- Remote MCP endpoint: `https://huagongshe.com/mcp`.
- MCP tool count remains exactly 13.
- Mixed authentication remains tool-level: anonymous public tools plus OAuth-protected private/write tools.
- Existing `hgs_*` AI Keys remain a runtime compatibility credential and are not advertised as the OpenAI OAuth connection scheme.
- OAuth scopes remain `read`, `reaction:write`, and `skill:write`.
- Notes remain outside the MCP surface; there is no `note:write` scope or Note tool in v1.7.0.
- No custom MCP UI resource is shipped in this package, so review screenshots are not supplied.

## Package

The portable submission package lives at `plugins/huagongshe/`. Its package version starts at `1.0.0` independently of the HGS product `VERSION` file:

- `plugin.json` — listing metadata, five positive review cases, three negative review cases, and release notes.
- `mcp.json` — one remote Streamable HTTP MCP server.
- `assets/icon.png` — square HGS app icon reused from the existing site asset.

The package deliberately contains no credentials, reviewer account instructions, demo recording URL, `.app.json`, lifecycle hooks, or screenshots.

## Tool annotation review

| Tool | readOnlyHint | openWorldHint | destructiveHint | Review justification |
| --- | --- | --- | --- | --- |
| `search_chemistry_data` | false | true | false | Exact misses may create an HCID and/or enqueue external-source work; structure modes themselves are reads. The tool can reach open chemistry sources indirectly through the existing enrichment path. It does not delete or overwrite user data. |
| `get_chemical` | false | true | false | `enrich=full` may enqueue external-source enrichment and persist queue state. `core` is read-only, but the tool contract includes the stateful `full` mode. No destructive mutation occurs. |
| `get_reaction` | true | false | false | Reads one bounded HGS reaction record, optionally including the authenticated owner's private record. |
| `render_molecule_svg` | true | false | false | Computes SVG from an HGS chemical or supplied SMILES and does not persist user-visible state. |
| `render_reaction_svg` | true | false | false | Computes SVG from an HGS reaction and does not persist user-visible state. |
| `list_skills` | true | false | false | Lists public skills or the authenticated user's own skills without mutation. |
| `get_skill` | true | false | false | Reads one accessible HGS skill package without mutation. |
| `calculate_stoichiometry` | true | false | false | Performs bounded local chemistry calculation and does not save a reaction. |
| `list_my_reactions` | true | false | false | Reads only reaction records owned by the authenticated HGS user. |
| `validate_reaction` | true | false | false | Validates/canonicalizes a draft without saving it. The write scope authorizes the domain but validation itself has no persistent side effect. |
| `validate_skill` | true | false | false | Validates a ZIP package without saving it or executing its scripts. |
| `create_skill` | false | false | false | Adds a private user-owned skill. Creation is idempotent with the supplied key and does not delete/overwrite existing data. |
| `create_reaction` | false | true | false | Adds one user-confirmed reaction and may create HCIDs/enqueue identity discovery. The write is additive and idempotent; it does not delete/overwrite an existing reaction. |

## Response-minimization audit

HCID and HRID are product identifiers needed to continue chemistry workflows. Reaction and skill outputs may also include timestamps that are part of the existing frozen HGS MCP contract.

`create_reaction` currently returns the existing service projection, including `created_by_user_id` and `created_via`. OpenAI review guidance prefers omitting internal account identifiers when they are not required. W5 does not silently change this frozen W3 return structure. Treat this as a live Scan Tools/manual-review checkpoint: if the reviewer flags the field, changing the MCP result contract requires an explicit compatibility decision rather than an OpenAI-only service fork.
## Review account contract

Reviewer credentials must be entered only in the OpenAI review dashboard, never committed to Git.

The dedicated review account must:

- be a real HGS account with no MFA/email/SMS/magic-link step required during review;
- contain at least one public and one private saved reaction so `list_my_reactions` can be verified;
- be allowed to authorize `read`, `reaction:write`, and `skill:write`;
- contain only sample/non-sensitive data;
- remain available for subsequent review runs.

## Domain verification

`/.well-known/openai-apps-challenge` is implemented as a public Next route. It serves the exact value of `HGS_OPENAI_APPS_CHALLENGE` with `text/plain` and `no-store` headers. When the variable is absent or malformed, the route fails closed instead of exposing a placeholder token.

The challenge token is generated by the OpenAI submission portal and must never be committed.

## Deployment-only gate

These steps require the release candidate to be deployed and therefore are not performed during repository-only W5 development:

1. Configure production `HGS_OPENAI_APPS_CHALLENGE` with the portal-generated value and verify the domain.
2. Confirm the production privacy policy matches actual operations, including the stated maximum 30-day operational-log retention.
3. Add the production MCP server in the OpenAI submission portal and configure mixed OAuth/no-auth.
4. Run **Scan Tools** against the deployed endpoint and verify exactly 13 tools, their titles/descriptions, schemas, annotations, `_meta.securitySchemes`, and server instructions.
5. Execute all five positive and three negative cases with the dedicated review account.
6. Record the required reviewer-accessible demo video from the deployed integration and enter its URL in review details or package metadata.
7. Enter reviewer credentials and sign-in instructions in the secure review form.
8. Only after the scan and review cases match this artifact may the plugin be submitted.

Marketplace approval timing is not a v1.7.0 code-release blocker. A truthful, deployable submission package and reproducible review material are.
