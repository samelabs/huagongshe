---
name: huagongshe-reaction-publisher
description: Extract and normalize chemical reactions from webpages, DOI or patent pages, PDFs, Word files, images, or pasted text, then validate and submit them to the user's Huagongshe reaction repository. Use when an AI agent needs to turn source material into a structured reaction, check chemical structures, preserve evidence, ask the user about missing facts, or publish through the Huagongshe API.
---

# Publish reactions to Huagongshe

Use `https://huagongshe.com/api` as the API base. Read these live contracts before acting:

- `GET /agent-guide` for behavioral rules and limits.
- `GET /openapi.json` for current request and response schemas.

Require a user-created API Token and send it as `Authorization: Bearer <token>`. Never print, store in source files, or send the token anywhere except `https://huagongshe.com`.

## Workflow

1. Read the supplied webpage, document, image, or pasted text. Keep its URL, DOI, patent number, title, or user attribution as source evidence.
2. Extract only stated facts. Do not invent structures, quantities, conditions, yields, procedures, or citations. Keep unknown optional fields empty.
3. Normalize each participant into one role: `REACTANT`, `PRODUCT`, `REAGENT`, `CATALYST`, or `SOLVENT`. Use `occurrence_count` for repeated identical structures in one role.
4. Express structures as SMILES. When a name or identifier is ambiguous, query `GET /search` and ask the user instead of guessing.
5. Build one reaction payload using the fields below. Require at least one reactant, one product, and a valid source.
6. Show the user a concise draft containing structures, roles, conditions, yield, source, and visibility. Explicitly ask whether it should be `public` or `private`; default to `private` when the user has not decided.
7. Call `POST /reactions/validate`. Resolve every validation error before publishing.
8. After the user confirms, call `POST /reactions` with a new `Idempotency-Key`. Reuse that same key for retries of the same submission.
9. Return the resulting HRID, URL, visibility, and any newly created HCIDs. Never report success without a successful API response.

## Payload

Each `participants` item accepts:

- `role`, `smiles`, and optional `occurrence_count`.
- Optional `amount_value` with `amount_unit`.
- Optional `equivalents`.
- Optional `concentration_value` with `concentration_unit`.
- Optional `yield_percent`, only for a `PRODUCT`.

The reaction accepts optional procedure, condition, temperature, duration, pH, atmosphere, pressure, workup, safety, and note fields. Paired values and units must be supplied together.

Use one `source_type`:

- `self` for the user's own experiment.
- `doi` with `doi`.
- `patent` with `patent`.
- `url` with `source_url`.
- `database` or `other` with `source_citation`.

## Boundaries

- Treat HCID and HRID returned by Huagongshe as the platform identities.
- Let the API perform final RDKit canonicalization and chemical matching.
- Do not create duplicate participant entries with the same role and canonical structure.
- Do not make a reaction public without explicit user confirmation.
- The current API Token supports query, validation, and creation. Direct the user to the website to edit, change visibility, or delete a reaction.
- Stop and explain the unresolved field when the source cannot support an accurate submission.
