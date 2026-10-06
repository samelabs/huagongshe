# HGS AIchem Plugin submission closeout

Repository package root: `plugin/`.

The package uses the portable Agent Plugins format: `plugin.json` + `mcp.json`. It intentionally contains no `.app.json`, registered-app reference, lifecycle hook, bundled skill, or screenshot. The single remote server is the production endpoint `https://huagongshe.com/mcp`.

## Repository-complete items

- Public listing metadata for HGS AIchem.
- Production MCP URL and mixed anonymous/OAuth tool metadata.
- Five positive and three negative review cases.
- Public website, support, privacy, and terms URLs.
- Primary/composer icon.
- OAuth 2.1 DCR + Authorization Code/PKCE S256 flow.
- Tool annotations and per-tool security schemes are emitted by the MCP server.
- No Note MCP tool or `note:write` scope in v1.7.0.

## Portal-only prerequisites

These are generated or entered in the OpenAI submission portal and must not be fabricated in the repository:

1. Select an OpenAI project with global data residency and the verified business publisher identity.
2. Upload a ZIP whose root is the contents of `plugin/`.
3. Connect `https://huagongshe.com/mcp` using mixed OAuth/no-auth.
4. Host the portal-generated domain token as exact plain text at the generated `/.well-known/openai-apps-challenge` URL, verify the domain, then remove/rotate only as the portal permits.
5. Run Scan Tools against the deployed v1.7.0 server and resolve every required finding.
6. Enter a dedicated HGS reviewer account in the secure portal form. It must contain sample data, require no MFA/email/SMS approval, and have the permissions needed by the review cases.
7. Add an accessible demo-recording URL. It is deliberately omitted from `plugin.json` until a real recording exists.
8. Add per-tool annotation justifications in the review form using the matrix below, then submit the draft.

## Annotation justification matrix

| Tool | Why the advertised hints are accurate |
| --- | --- |
| search_chemistry_data | Not read-only because exact misses can create/queue source work; open-world because source discovery may reach external chemistry providers; not destructive. |
| get_chemical | Not read-only because enrich=full can enqueue source enrichment; open-world for provider enrichment; not destructive. |
| get_reaction | Read-only; visibility-aware lookup inside HGS; no user-visible mutation. |
| render_molecule_svg | Read-only; deterministic rendering of supplied/HGS structure; closed-world aside from bounded HGS input. |
| render_reaction_svg | Read-only; visibility-aware HGS reaction rendering; closed-world. |
| list_skills | Read-only list of public or caller-owned HGS skills; closed-world. |
| get_skill | Read-only retrieval of an accessible HGS skill; closed-world. |
| calculate_stoichiometry | Read-only deterministic calculation from caller input; closed-world. |
| list_my_reactions | Read-only list of caller-owned HGS reactions; closed-world. |
| validate_reaction | Read-only validation/canonicalization; requires reaction:write under the frozen HGS scope model but does not save. |
| validate_skill | Read-only package validation; requires skill:write under the frozen HGS scope model but does not save. |
| create_skill | Additive, idempotent create of a private HGS skill; not destructive; closed-world. |
| create_reaction | Additive, idempotent create; may create HCIDs/queue identity discovery, so open-world; not destructive. |

## Release gate

Before production release: run `scripts/migrate.py` against the production database so both v1.7.0 forward migrations are applied, deploy the audited tree, verify public OAuth metadata and `/mcp`, then Scan Tools. Do not bump `VERSION` or tag v1.7.0 before this release gate passes.
