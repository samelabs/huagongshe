# Huagongshe Design System v2

Status: Draft for implementation
Scope: Public site + entity pages + search + docs + workspace visual language. Admin remains a separate high-density surface.

## 1. Goal

Huagongshe already has a complete product structure and strong data capability. The design problem is no longer missing pages or missing features; it is that visual rules were accumulated page by page.

Design System v2 makes the site feel like one mature chemical-data product rather than a collection of finished feature pages.

Primary goals:

1. Human-readable first. Public pages are optimized for people reading chemical and reaction data.
2. Data semantics drive hierarchy. Source systems do not define the top-level visual structure.
3. One visual grammar across Chemical, Reaction, Search, Guide and Workspace.
4. Dense enough for professional chemical data, but not admin-density.
5. Border-led, low-shadow, precise visual language.
6. Mobile remains a data interface, not a centered marketing hero.
7. Source provenance and conflicts remain visible; the UI must not silently merge conflicting facts.

Non-goals:

- No database schema changes.
- No identity-governance changes.
- No API/MCP semantic changes.
- No broad admin redesign in the first implementation phases.
- No AI-first interaction imposed on public detail pages.

## 2. Page families

All pages must belong to one of five families.

### 2.1 Discovery

Examples: home, search.

Purpose: find a chemical or reaction.

Characteristics:
- Search is the visual anchor.
- Medium information density.
- No persistent sidebar.
- Result cards represent entities, not generic content blocks.

### 2.2 Entity

Examples: `/chemical/[id]`, `/reaction/[id]`.

Purpose: understand one canonical entity.

Shared structure:
1. Breadcrumb
2. Entity Header
3. Local navigation
4. Main semantic content
5. Secondary rail
6. Sources/provenance

### 2.3 Workspace

Examples: `/aichem`, personal reactions, saved data, account workflows.

Purpose: do work.

Characteristics:
- Higher density than public pages.
- Tool actions may dominate.
- Reuses entity cards, data rows, form controls and notices from the system.

### 2.4 Documentation

Examples: guide, MCP guide, skills documentation.

Purpose: learn and execute.

Characteristics:
- Reading measure.
- Stable typography for prose/code/steps/callouts.
- Avoid excessive cardization.

### 2.5 Operations

Examples: admin, pipeline.

Purpose: monitor and operate.

Characteristics:
- Compact density.
- May retain 12–13 px operational text.
- Visually related to the product but not used as the reference density for public pages.

## 3. Foundation tokens

The implementation may retain current brand colors, but token names and usage must become semantic.

### 3.1 Color roles

Primary blue:
- interactive links
- primary buttons
- selected/focus states
- chemical entity accent

Neutral ink:
- headings
- body text
- data values

Neutral muted:
- labels
- metadata
- provenance

Reaction gray-blue:
- reaction entity accent only
- HRID and reaction-specific cues

Green/orange:
- real semantic state only
- not general decoration

Surfaces:
- page background: light neutral wash
- content surface: white
- panel surface: subtle neutral
- borders carry structure more often than shadows

### 3.2 Typography scale

Use the following public-product scale as the default:

- 12 px: caption / provenance / compact metadata
- 13 px: secondary metadata
- 14 px: data value / compact body
- 16 px: main body
- 18 px: H3 / entity-card title
- 22 px: H2 / major section heading
- 30 px: page title
- 34–36 px: entity primary name where appropriate
- 36–40 px: home hero only

Rules:
- Do not use 8 px visible text.
- Public detail pages should not inherit admin density.
- Monospace is reserved for IDs, SMILES, InChIKey, DOI-like identifiers and code.

### 3.3 Spacing scale

Allowed layout spacing values:

`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64`

Prefer these values for gap, padding and section rhythm. New arbitrary values require a layout-specific reason.

Typical usage:
- label → value: 4–8
- row padding: 12–16
- compact group: 24
- section spacing: 48
- major page boundary: 64

### 3.4 Radius

Default radius system:
- 6 px: compact controls, tags, small badges
- 10 px: buttons, inputs, panels, cards
- 14 px: only major search/hero surfaces when visually justified

Chemical-data UI should remain precise rather than overly rounded.

### 3.5 Shadow

Default: no shadow.

Use shadow only for floating UI:
- dropdown
- menu
- popover
- temporary overlay

Cards and panels should use borders and surface contrast.

## 4. Layout widths

Reduce the current collection of page-specific widths to named layout roles.

Recommended roles:

- `--layout-reading`: ~760 px
- `--layout-content`: ~1040 px
- `--layout-wide`: ~1180 px
- `--rail-width`: ~260–280 px

Rules:
- Documentation prose uses reading width.
- Search/content lists use content width.
- Entity pages use wide width.
- Individual components must not invent new page-level max widths.

## 5. Core primitives

The implementation should converge on reusable primitives. Names are conceptual; exact file names may vary.

### 5.1 PageShell

Owns:
- page max width
- horizontal gutters
- vertical top/bottom spacing

### 5.2 PageHeader

Used by non-entity pages.

Contains:
- optional kicker
- H1
- optional description
- optional utility action

### 5.3 EntityHeader

Shared by Chemical and Reaction.

Owns:
- entity reference ID
- primary human-readable title
- secondary title / descriptors
- key facts
- visual (molecule/equation)
- lightweight utility actions

Do not force Chemical and Reaction into identical proportions; share the visual grammar, not the exact geometry.

### 5.4 EntityId

HCID/HRID are platform record references, not chemical identifiers.

Rules:
- HCID = canonical Huagongshe chemical record id (`chemistry.chemicals.id`).
- HRID = canonical Huagongshe reaction record id (`chemistry.reactions.id`).
- Never present HCID beside CAS/CID/InChIKey as if all carry the same chemical meaning.
- No zero-padding.
- No synthetic encoding.
- Small monospace number, quiet visual treatment.
- Full version for entity header; compact version for cards/lists.
- Chemical and reaction variants may have different accent colors, but identical spacing/typography rules.
- Accessible label should explain the platform record type.

### 5.5 Section

Default content grouping.

Most sections are plain and do not need a surrounding card.

### 5.6 SectionHeader

Default:
- H2 only
- optional count/status on the right

Kickers are optional taxonomy cues, not mandatory decorations on every section.

### 5.7 DefinitionList / DataRow

Standard factual row:

`label | value`

Desktop:
- label column ~160–180 px
- value flexible

Mobile:
- short fields may stay two-column
- long identifiers and code-like fields stack label above value

### 5.8 CodeField

For:
- SMILES
- Reaction SMILES
- InChIKey
- DOI / long external identifiers

Rules:
- monospace
- wrap safely
- optional copy action
- never squeeze into a narrow fixed value column on mobile

### 5.9 SourceTag / Evidence

Source is secondary evidence, not a top-level page organizer.

Examples:
- PubChem
- ChemicalBook
- ORD
- DSSTox

Source chips must remain visually quiet.

If sources disagree, render separate values with source attribution. Do not silently collapse conflicts.

### 5.10 Surface

Only three semantic surface levels:

1. Plain section — default body content
2. Data panel — tightly related facts such as descriptors/conditions
3. Entity card — another object the user can open

Do not wrap every section in a card.

### 5.11 EntityCard

Reserved for navigable entities:
- chemical
- reaction
- supplier
- user
- skill where applicable

A card should visually imply “this is another object”.

### 5.12 LocalNav

Used on long entity pages.

Desktop:
- may be part of the sticky secondary rail

Tablet/mobile:
- horizontal scroll or compact in-flow navigation

### 5.13 SecondaryRail

Purpose: reading assistance, not promotional content.

May contain:
- local page navigation
- key identifiers
- source/data status
- record metadata

Do not make AI actions the primary purpose of the public entity rail.

## 6. Chemical Detail reference page

### 6.1 Role

Human-readable view of one canonical chemical entity.

The page hierarchy is semantic-first, not source-first.

### 6.2 Header

Recommended desktop composition:
- molecule visual: 320–340 px region
- title area: remaining width

Title area order:
1. HCID
2. preferred human-readable name
3. secondary IUPAC name when different
4. primary facts: formula / molecular mass / primary CAS
5. utility actions such as follow/share

Avoid a row of many equal-weight actions in the header.

### 6.3 Main content order

1. Overview
2. Names & Identifiers
3. Properties
4. Safety & Regulatory
5. Chemistry & Industry
6. Reactions
7. Sources

Exact placement of Reactions may move earlier when product evidence supports it, but it must not remain buried after all source-specific sections.

### 6.4 Data composition

ChemicalBook and PubChem must not each define duplicated top-level visual sections.

Example:

Bad:
- ChemicalBook Properties
- PubChem Experimental Properties

Preferred:
- Properties
  - Melting point — value — source(s)
  - Boiling point — value — source(s)

Where facts cannot be normalized safely, keep separate source-attributed values.

### 6.5 Long evidence

PubChem evidence categories and prose should not default-open multiple long blocks per section.

Default presentation:
- important facts visible
- long prose summarized/collapsed
- full evidence expandable

### 6.6 Names

CB aliases and existing SynonymExplorer should converge conceptually into one “Names & Synonyms” section.

Avoid visually presenting duplicate alias systems to the user.

## 7. Reaction Detail reference page

### 7.1 Role

Human-readable experimental reaction record.

The existing semantic order is broadly correct and should be preserved.

### 7.2 Header

Order:
1. HRID
2. reaction record title / neutral label
3. compact factual summary where available
4. utility actions

Do not invent reaction names with AI.

A factual summary may be assembled from structured data, e.g. reactant/product counts, catalyst, solvent, temperature, duration, yield.

### 7.3 Equation

Reaction equation remains the primary visual and may span the content width.

### 7.4 Main content order

1. Equation
2. Reactants / Products
3. Auxiliaries
4. Conditions
5. Procedure
6. Workup
7. Safety / Notes
8. Sources

### 7.5 Secondary rail

Use for:
- local nav
- creator / ownership where relevant
- HRID and record state
- ORD / dataset / DOI / patent / source citation

Reaction SMILES should use the standard CodeField pattern.

## 8. Search and entity-result cards

Search results should visually reuse the same entity vocabulary as detail pages.

Chemical result:
- molecule thumbnail
- preferred name
- compact HCID
- formula / CAS / selected identifiers

Reaction result:
- reaction preview
- compact HRID
- factual metadata

Do not create a separate visual language for search results.

## 9. Header/navigation

The current header is too sparse for the matured information architecture.

Desktop navigation should be reconsidered around stable product destinations, for example:
- Data/Search
- Skills
- Guide
- Workspace
- Account

Exact labels must follow product naming, but the header should expose the real site structure rather than only Guide + login.

Brand treatment should be reviewed separately. “化工社AIchem” should not be assumed immutable merely because it is the current wordmark.

## 10. Home page

Keep the current tool-first simplicity.

Home is not a marketing landing page.

Recommended hierarchy:
1. Brand/product proposition
2. Search
3. supported query hints
4. key data scale / openness facts
5. AI access methods (MCP / Skills / API as appropriate)
6. personal workspace entry

Avoid decorative sections that do not help discovery or comprehension.

## 11. Documentation pages

Use reading-width prose and stable documentation patterns:
- page header
- section
- step
- code/prompt block
- callout
- reference table

Reduce card count where a normal document hierarchy is clearer.

## 12. Responsive rules

Breakpoints should reflect three modes rather than page-specific behavior.

### Wide (>= 1024)
- entity header may be multi-column
- sticky secondary rail allowed
- entity page uses wide layout

### Medium (640–1023)
- content becomes single primary column
- secondary rail becomes in-flow or local horizontal nav
- entity header may remain two-column when content fits

### Small (< 640)
- entity header is vertical
- text remains left-aligned
- data/code fields may stack
- local nav may horizontally scroll
- actions wrap without becoming a centered marketing cluster

Critical rule:
- Chemical and Reaction detail content remains left-aligned on mobile.

## 13. Accessibility and interaction

- Minimum practical touch target ~40–44 px for primary controls.
- Visible focus treatment uses primary accent.
- Color is never the only distinction between Chemical and Reaction.
- Long identifiers wrap without causing horizontal page overflow.
- Disclosure controls must be keyboard accessible.
- Heading order remains semantic.

## 14. Implementation architecture

The current large `globals.css` should be reduced over time rather than expanded indefinitely.

Recommended target organization (exact filenames may differ):

```
web/styles/
  tokens.css
  base.css
  primitives.css
  patterns.css
  pages/
    discovery.css
    entity.css
    docs.css
    workspace.css
    operations.css
```

React should increasingly compose shared primitives rather than create new page-specific visual patterns.

Do not perform a big-bang CSS deletion. Migrate reference pages first, then remove dead legacy rules after verified adoption.

## 15. Migration phases

### Phase 1 — Foundation

Create/normalize:
- semantic colors
- typography scale
- spacing scale
- radius
- borders/surfaces
- layout widths
- buttons/inputs
- Section/SectionHeader
- EntityId

No major page composition change required yet.

### Phase 2 — Entity reference pages

Refactor:
- Chemical Detail
- Reaction Detail

These two pages are the reference implementation of Design System v2.

Acceptance:
- shared entity primitives
- semantic-first Chemical layout
- Reaction keeps experimental workflow semantics
- HCID/HRID normalized
- responsive rules unified
- no new source-first duplicate section hierarchy

### Phase 3 — Discovery

Refactor:
- search page
- ChemicalResult
- ReactionResult
- home

### Phase 4 — Documentation

Refactor:
- guide
- MCP guide
- skills presentation

### Phase 5 — Workspace

Refactor user/workbench surfaces using the stabilized primitives.

### Phase 6 — Cleanup

- remove dead legacy CSS
- consolidate duplicated tokens
- document exceptions

Admin/pipeline only adopts safe global primitives unless separately approved.

## 16. Design invariants

These are release gates, not preferences.

1. Human entity pages are semantic-first, not source-first.
2. HCID/HRID are platform record references, never chemical/reaction scientific identifiers.
3. One fact has one primary visual home; provenance is attached to it.
4. Conflicting source facts remain distinguishable.
5. Public detail text is not admin-density.
6. Mobile detail pages remain left-aligned and readable.
7. Cards represent meaningful grouped surfaces or navigable entities, not decoration.
8. New spacing/radius/font sizes should come from the system scale.
9. No new page-level max-width constants without a named layout role.
10. Chemical and Reaction share a system but preserve different domain semantics.

## 17. Reference acceptance checklist

Before Design System v2 is considered established, verify at minimum:

- Home desktop/mobile
- Search results desktop/mobile
- simple chemical (e.g. small molecule)
- complex chemical with long IUPAC name and rich data
- chemical with sparse data
- public ORD reaction
- personal/private reaction
- reaction with many participants
- long SMILES / InChIKey / source URL
- empty/enrichment-loading states

The goal is not pixel identity across pages. The goal is a recognizable, coherent Huagongshe visual system with stable rules.