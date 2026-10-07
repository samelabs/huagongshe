"""REST / AI Key compatibility surface for non-MCP clients.

产品定位: 主要 Agent 接入层是 MCP(https://huagongshe.com/mcp)。
本 router 服务于不支持 MCP 的 AI 客户端、用户自己的 HTTP automation、
以及既有 hgs_* AI Key 客户端; 是兼容面, 不是与 MCP 平级的新 Agent 平台。
(Contract text is served in English; this module docstring stays internal.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text

from .core.config import settings
from .core.database import get_db
from .core.security import Actor, public_or_actor


router = APIRouter(tags=["agent"])



@router.get(
    "/agent-guide",
    operation_id="get_agent_connection_guide",
    summary="REST / AI Key compatibility surface: read AI-available operations (MCP is the primary integration)",
)
async def agent_guide(
    authorization: str | None = Header(default=None),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    """Return the complete, bounded operation guide; a Bearer token also confirms its owner."""
    bearer_supplied = bool(authorization and authorization.lower().startswith("bearer "))
    if bearer_supplied and actor is None:
        raise HTTPException(401, "AI Key is invalid, expired, or deleted")

    agent = actor if actor and actor.auth_kind == "agent" else None
    origin = settings.public_base_url.rstrip("/")
    api_base = f"{origin}/api"
    publisher_skill_id = await db.execute(text(
        "SELECT id FROM community.skills WHERE slug='huagongshe-reaction-publisher' LIMIT 1"
    ))
    publisher_skill_id = publisher_skill_id.scalar()
    skill_url = (
        f"{origin}/api/skills/{publisher_skill_id}"
        if publisher_skill_id is not None
        else f"{api_base}/skills?scope=public&q=reaction-publisher"
    )
    return {
        "api_version": settings.api_version,
        "api_base_url": api_base,
        "connection": {
            "status": "authenticated" if agent else "public_ready",
            "account": (
                {
                    "id": agent.id,
                    "username": agent.username,
                    "display_name": agent.display_name,
                }
                if agent else None
            ),
            "instruction": (
                "Connection confirmed. Use only the operations listed below; capabilities are bounded by this contract."
                if agent
                else "Public operations work without authentication. To access personal data or authorized operations, create an AI Key in account settings, then read this entry again with Authorization: Bearer <AI Key> to confirm the connection."
            ),
        },
        "authentication": {
            "type": "bearer",
            "header": "Authorization: Bearer <AI Key>",
            "scopes": list(agent.scopes) if agent else ["read", "reaction:write", "skill:write"],
            "token_handling": "Send the AI Key only to huagongshe.com; never write it into public prompts, code, files, or logs.",
        },
        "discovery": {
            "skill_help_url": f"{origin}/skills",
            "optional_skill_url": skill_url,
            "instruction": "Choose an operation from the list below; capabilities are bounded by this contract, not by OpenAPI.",
        },
        "operations": [
            {
                "id": "search_chemistry_data",
                "method": "GET",
                "path": "/api/search",
                "auth": "public_or_bearer",
                "purpose": "Search compounds and reactions by name, CAS, HCID, CID, InChIKey, DOI, SMILES, or structure",
                "input": "q is required; mode is exact, substructure, or similarity; page defaults to 1 with max 20; page_size defaults to 30 with max 100; total=None means the full count was not computed for the current mode, and has_more is the authoritative next-page indicator; capped=true appears only in substructure mode and means the product return cap (250) was reached — the true database match count is unknown and total must not be treated as the real total",
            },
            {
                "id": "get_chemical",
                "method": "GET",
                "path": "/api/chemicals/{chemical_id}",
                "auth": "public_or_bearer",
                "purpose": "Read one HCID's structure, identifiers, properties, and related reaction overview",
                "input": "enrich=core (default, canonical data only) or full (unified semantic detail: descriptions/names and synonyms/properties/safety and regulatory/industrial applications/suppliers/provenance; each source keeps its own values and attribution)",
            },
            {
                "id": "get_reaction",
                "method": "GET",
                "path": "/api/reactions/{reaction_id}",
                "auth": "public_or_bearer",
                "purpose": "Read one HRID; the AI Key's owner may also read their own private records",
            },
            {
                "id": "render_molecule_svg",
                "method": "GET",
                "path": "/api/mol/{chemical_id}/svg?w=&h=",
                "auth": "public",
                "purpose": "Get the 2D structure image (SVG) of a compound; w/h set the size",
            },
            {
                "id": "render_reaction_svg",
                "method": "GET",
                "path": "/api/reactions/{reaction_id}/svg?w=&h=",
                "auth": "public",
                "purpose": "Get the 2D structure image (SVG) of a reaction equation; w/h set the size",
            },
            {
                "id": "list_my_reactions",
                "method": "GET",
                "path": "/api/users/me/reactions",
                "auth": "bearer",
                "purpose": "Read the AI Key owner's own reaction records",
                "input": "visibility is all, private, or public; supports page and page_size",
            },
            {
                "id": "list_skills",
                "method": "GET",
                "path": "/api/skills",
                "auth": "public_or_bearer",
                "purpose": "List skills: scope=public browses the platform's public skill pool (official and open community skills); scope=mine reads the AI Key owner's own skills",
                "input": "scope is public or mine (mine requires an AI Key); q keyword search; category filter; supports page and page_size",
            },
            {
                "id": "get_skill",
                "method": "GET",
                "path": "/api/skills/{skill_id}",
                "auth": "public_or_bearer",
                "purpose": "Read a skill's manifest, file tree, and full SKILL.md text; the AI Key owner may also read their own private skills",
            },
            {
                "id": "download_skill_archive",
                "method": "GET",
                "path": "/api/skills/{skill_id}/archive",
                "auth": "public_or_bearer",
                "purpose": "Download a skill's complete zip for loading into the user's local AI environment; skills containing scripts must be reviewed by a human before execution",
            },
            {
                "id": "calculate_stoichiometry",
                "method": "POST",
                "path": "/api/stoichiometry/scale",
                "auth": "public_or_bearer",
                "purpose": "Scale calculation: list all reaction components by role and, using any single component's charge (limiting reagent or target product) as the molar basis, convert the full charge table and report the theoretical product yield",
                "input": "components[{role(REACTANT/REAGENT/CATALYST/SOLVENT/PRODUCT),smiles,eq,label?}] (max 30; eq required for non-solvents) + basis{index,amount_value,amount_unit(g/mg/mol/mmol)} + optional concentration_mol_per_l (solvent volume is derived from concentration)",
            },
            {
                "id": "validate_reaction",
                "method": "POST",
                "path": "/api/reactions/validate",
                "auth": "bearer:reaction:write",
                "purpose": "Validate a reaction draft and return the RDKit-normalized reaction SMILES and participants",
            },
            {
                "id": "validate_skill",
                "method": "POST",
                "path": "/api/skills/validate",
                "auth": "bearer:skill:write",
                "purpose": "Validate a skill zip draft (not saved): structure, quotas, file count, frontmatter, script syntax, and dangerous-call warnings",
                "input": "multipart field file=<skill zip>",
            },
            {
                "id": "create_skill",
                "method": "POST",
                "path": "/api/skills",
                "auth": "bearer:skill:write",
                "purpose": "Save a user-confirmed skill zip into that user's skill container; personal skills are always private",
                "required_header": "Idempotency-Key; reuse it for retries of the same save, never across different skills",
            },
            {
                "id": "create_reaction",
                "method": "POST",
                "path": "/api/reactions",
                "auth": "bearer:reaction:write",
                "purpose": "After user confirmation, save an already-validated draft into the user's reaction library",
                "required_header": "Idempotency-Key; reuse it for retries of the same save, never across different drafts",
            },
        ],
        "payload_hints": {
            "required": ["visibility", "participants", "source_type"],
            "participant_required": ["role", "smiles"],
            "participant_roles": ["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"],
            "minimum_structure": "At least one REACTANT and one PRODUCT",
            "visibility": "Use private unless publicity has been confirmed; public requires the user's explicit confirmation",
            "paired_fields": [
                "amount_value + amount_unit",
                "concentration_value + concentration_unit",
                "temperature_value + temperature_unit",
                "duration_value + duration_unit",
                "pressure_value + pressure_unit",
            ],
            "source_types": {
                "self": "the user's own experiment",
                "doi": "also provide doi",
                "patent": "also provide patent",
                "url": "also provide source_url",
                "database": "also provide source_citation",
                "other": "also provide source_citation",
            },
        },
        "workflow": [
            "Read the web page, document, image, or text provided by the user and keep the source evidence",
            "Extract only explicit facts; ask the user first when the structure is ambiguous or required fields are missing",
            "Build a structured draft; set visibility=private until the user decides to publish",
            "Show the participants, conditions, source, and visibility to the user and obtain save confirmation",
            "Call POST /api/reactions/validate with the same payload",
            "Once validation passes, call POST /api/reactions with a unique Idempotency-Key",
            "Return the HRID, page URL, visibility, and created_chemical_ids",
        ],
        "rules": [
            "Never invent SMILES, sources, conditions, quantities, yields, or experimental procedures; omit unknown optional fields.",
            "If multiple plausible structures are found, let the user choose instead of guessing by result order.",
            "Do not split the same role and canonical structure into duplicate participants; use occurrence_count.",
            "Validation never saves; only POST /api/reactions creates a record.",
            "The AI Key only allows querying, validating, and creating; editing, visibility changes, and deletion are done on the website.",
            "Do not claim a save succeeded without a success response.",
        ],
        "errors": {
            "400_or_422": "Fix the fields or structure per the detail and validate again; do not guess missing facts",
            "401": "Stop; the AI Key is invalid, expired, or deleted — ask the user to re-authorize",
            "403": "Stop; the current authorization does not permit this action; do not try to bypass via other endpoints",
            "404": "Double-check the stable identifier; do not guess adjacent IDs",
            "409": "Handle duplicate participants or idempotency conflicts per the detail",
            "429": "Honor Retry-After and reduce the request rate",
        },
        "rate_limits": {
            "reaction_writes_per_minute": settings.api_reaction_write_limit_per_minute,
            "reaction_writes_per_day": settings.api_reaction_write_limit_per_day,
            "stoichiometry_per_minute": settings.api_stoich_limit_per_minute,
            "skill_writes_per_hour": settings.api_skill_write_limit_per_hour,
        },
    }
