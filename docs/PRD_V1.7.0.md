# HGS v1.7.0 PRD

Status: execution baseline  
Base release: v1.6.0 @ `554900570a135cc36c7a296d2f80c4122ca95637`

## 1. Version goal

v1.7.0 closes two product gaps without coupling them:

1. **Notes + Workbench** — low-friction user context around HCID/HRID.
2. **Agent access** — normalize the existing MCP contract, add standards-based OAuth, and prepare the OpenAI Plugin distribution layer.

The two lines share existing business services only. Neither is a release dependency of the other.

## 2. Product objects

- **HCID** — compound fact node.
- **HRID** — structured reaction fact node.
- **Note** — flexible human context that may reference HCID and/or HRID.

Reaction remains the structured, computable record. Note stores observations, decisions, sources, plans, supplier/customer context, experimental judgment, or other working context.

Existing `chemistry.reactions.note` keeps its current meaning as an internal field of one structured reaction record. It is not migrated to the new Notes domain.

## 3. Notes domain

### 3.1 Persistence

`community.notes`

- id
- owner_user_id
- visibility: public | private
- moderation_status: visible | hidden
- content: plain text, 1..30000 characters
- created_at / updated_at

References are real FK tables:

- `community.note_chemicals(note_id, chemical_id)`
- `community.note_reactions(note_id, reaction_id)`

A Note may exist with zero references. References add chemical context but do not own Note lifecycle. Maximum total references: 20.

No title, tags, attachments, Markdown, comments, likes, feed, collaborative editing, AI generation, or Note search in v1.7.0.

### 3.2 Visibility and privacy

Private Notes are owner-only.

A private Note may reference:
- any HCID;
- a public visible HRID;
- the Note owner's own private HRID.

A public Note may reference only public visible HRIDs at write time.

**Read-time privacy is also mandatory:** if a referenced reaction later becomes private or hidden, public Note serialization must stop exposing that HRID immediately. A signed-in viewer may see a private reaction reference only when that viewer owns the reaction. Reaction visibility changes must not call Notes service; this rule stays inside Notes read serialization to preserve module independence.

### 3.3 Lifecycle

Create/update:
- validate all references first;
- update fields and references in one transaction;
- reference updates use replace-set semantics.

Delete:
- owner only;
- physical delete;
- reference rows cascade.

Deleting an HRID removes only the relation row, not the Note.

### 3.4 Chemical identity governance

`community.note_chemicals` is registered in `CHEMICAL_REFERENCE_TABLES` as `DEDUPE_REKEY` with dedupe key `note_id`.

HCID merge must rekey and deduplicate Note relations without changing Notes business logic.

## 4. Notes API

Independent files:

- `api/notes.py`
- `api/schemas/notes.py`
- `api/services/notes.py`

`services.notes` is transport-neutral.

v1.7.0 HTTP surface:

- POST /api/notes
- GET /api/notes/{note_id}
- PUT /api/notes/{note_id}
- DELETE /api/notes/{note_id}
- GET /api/users/me/notes
- GET /api/chemicals/{chemical_id}/notes
- GET /api/reactions/{reaction_id}/notes

Web mutations are session-only. v1.7.0 does not add Note MCP tools or a `note:write` Agent scope.

## 5. Workbench information architecture

### Workspace
- Home
- Notes
- Reactions
- Saved

### Tools
- Search
- Stoichiometry

### Agent
- Skills

### Network
- Activity
- Following
- Followers

### Account
- Profile
- Avatar
- Security
- API Keys

Existing tab IDs and URLs stay stable where possible, especially `tab=mine`.

### 5.1 Notes UI

Notes is an autonomous panel in the existing registry architecture.

Required:
- NotesPanel owns its loading/error/pagination/visibility state.
- NoteEditor owns Note create/update form state.
- EntityReferencePicker uses the existing Search API to discover HCID/HRID; users must not be forced to know numeric IDs.
- Home shows Recent Notes before Recent Reactions.
- Top navigation exposes New Note and New Reaction as separate actions.
- No Note badge/dashboard count in v1.7.0.

Reuse infrastructure and APIs, not another panel's state.

### 5.2 Entity pages

Chemical and reaction pages may embed a generic `EntityNotes` presentation component.

- public + visible Notes only;
- contextual Add Note links into the same NoteEditor;
- chemical/reaction pages do not own Note CRUD;
- no social feed or ranking.

## 6. MCP contract

Existing tool count remains exactly 13.

Frozen:
- tool names;
- responsibilities;
- parameters/enums;
- result structures;
- `get_chemical(core|full)`;
- resource/rate gates.

Normalize only the agent-facing contract:
- English server title/instructions;
- English tool titles/descriptions/errors;
- source-faithful multilingual returned chemistry data;
- truthful annotations based on actual side effects;
- real Streamable HTTP protocol tests: initialize → tools/list → tools/call.

English error normalization must preserve original error semantics and useful dynamic context. Do not replace specific validation failures with generic messages.

Do not advertise OAuth security schemes before the OAuth runtime can actually honor them.

## 7. OAuth

OAuth is a standards-based MCP identity layer, not a global login wall and not an OpenAI-specific account model.

Required:
- protected-resource metadata;
- authorization-server metadata;
- Authorization Code + PKCE S256;
- resource/audience/issuer/scope validation;
- existing HGS web account/session for authorization UI;
- OAuth token resolves to existing HGS Actor;
- existing AI Key remains supported;
- public initialize/read capabilities remain anonymous;
- per-tool auth policy.

Initial scopes stay aligned with existing capabilities:
- read
- reaction:write
- skill:write

No `note:write` in v1.7.0.

Sign in with ChatGPT, if used later, is only an optional HGS login method and never replaces the HGS Authorization Server.

## 8. OpenAI Plugin layer

Plugin is a distribution/review layer over standard HGS MCP.

OpenAI-specific material may include listing metadata, privacy/company information, starter prompts, review test cases/test account, and scanner compatibility metadata.

It must not introduce OpenAI-specific business logic into chemistry, reaction, Notes, or identity services.

Marketplace approval timing is not a code-release blocker. Submission-readiness is.

## 9. Execution gates

### Notes domain
- CRUD/privacy/reference tests green;
- public read-time HRID privacy regression covered;
- identity merge rekey/collision tests green.

### Workbench
- TypeScript/build green;
- private Note create/edit/delete loop;
- Search-based HCID/HRID linking;
- contextual Add Note from chemical/reaction;
- public EntityNotes;
- desktop/mobile navigation regression-free.

### MCP
- exact 13-tool surface;
- metadata/annotations tests;
- protocol-level initialize/tools/list/tools/call;
- English errors preserve semantics.

### OAuth
- anonymous public tools remain anonymous;
- OAuth protected tools work;
- AI Key compatibility remains green;
- invalid/expired/wrong-audience/missing-scope cases fail closed.

## 10. Explicit non-goals

- Note feed/comments/likes/tags/attachments/Markdown/search/recommendation
- Note MCP tools
- Note OAuth scope
- Reaction redesign
- identity resolver redesign
- chemical data model redesign
- Skill redesign
- general social redesign
- production deployment architecture changes

Anything outside this PRD requires a separate decision instead of being absorbed into an implementation commit.
