"""Public read API for the autonomous chemicals and reactions data model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from .cache import cache_get, cache_set
from .chemistry import CAS_RE, DTXSID_RE, INCHIKEY_RE, canonicalize_smiles
from .config import settings
from .database import get_db
from .enrichment import (
    DEFAULT_SECTIONS,
    enqueue_chemical_if_needed,
)

router = APIRouter(tags=["chemistry"])

IDENTIFIER_ARRAYS = {
    "cas": "cas_numbers",
    "nikkaji": "nikkaji_numbers",
    "chembl": "chembl_ids",
    "ec": "ec_numbers",
    "unii": "unii_codes",
    "chebi": "chebi_ids",
}
FULL_DETAILS_SECTIONS = (
    "computed", "identifiers", "synonyms", "physical", "safety",
    "toxicity", "regulatory", "pharmacology", "uses",
)
CHEMICAL_SELECT = """
    c.id, c.pubchem_cid, c.smiles, c.pubchem_smiles,
    c.preferred_name, c.iupac_name, c.molecular_formula,
    c.average_mass, c.monoisotopic_mass, c.inchikey, c.dtxsid,
    c.cas_numbers, c.nikkaji_numbers, c.chembl_ids, c.ec_numbers,
    c.unii_codes, c.chebi_ids
"""


def chemical_dict(row: Any, score: float | None = None) -> dict[str, Any]:
    return {
        "id": row[0],
        "pubchem_cid": row[1],
        "smiles": row[2],
        "pubchem_smiles": row[3],
        "preferred_name": row[4],
        "iupac_name": row[5],
        "molecular_formula": row[6],
        "average_mass": float(row[7]) if row[7] is not None else None,
        "monoisotopic_mass": float(row[8]) if row[8] is not None else None,
        "inchikey": row[9],
        "dtxsid": row[10],
        "cas_numbers": row[11] or [],
        "nikkaji_numbers": row[12] or [],
        "chembl_ids": row[13] or [],
        "ec_numbers": row[14] or [],
        "unii_codes": row[15] or [],
        "chebi_ids": row[16] or [],
        "similarity": round(float(score), 4) if score is not None else None,
    }


async def fetch_chemicals(db: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (await db.execute(text(sql), params)).fetchall()
    return [chemical_dict(row, row[17] if len(row) > 17 else None) for row in rows]


async def reaction_summaries(
    db: Any,
    chemical_ids: list[int],
    role: str,
    page: int,
    page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    if not chemical_ids:
        return 0, []
    role_clause = ""
    params: dict[str, Any] = {"chemical_ids": chemical_ids}
    if role != "any":
        role_clause = "AND rc.role = :role"
        params["role"] = role.upper()
    total = int((await db.execute(text(f"""
        SELECT count(DISTINCT rc.reaction_id)
        FROM chemistry.reaction_chemicals rc
        WHERE rc.chemical_id = ANY(:chemical_ids) {role_clause}
    """), params)).scalar() or 0)
    params.update(limit=page_size, offset=(page - 1) * page_size)
    rows = (await db.execute(text(f"""
        WITH ids AS MATERIALIZED (
            SELECT DISTINCT rc.reaction_id
            FROM chemistry.reaction_chemicals rc
            WHERE rc.chemical_id = ANY(:chemical_ids) {role_clause}
            ORDER BY rc.reaction_id
            LIMIT :limit OFFSET :offset
        )
        SELECT DISTINCT ON (rx.id)
            rx.id, rx.reaction_smiles,
            COALESCE(NULLIF(cs.doi,''),rp.doi),
            COALESCE(NULLIF(cs.patent,''),rp.patent),
            CASE WHEN o.id IS NULL AND cs.id IS NOT NULL THEN '社区审核' ELSE d.name END,
            (SELECT array_agg(DISTINCT rc.role ORDER BY rc.role)
             FROM chemistry.reaction_chemicals rc
             WHERE rc.reaction_id=rx.id AND rc.chemical_id=ANY(:chemical_ids))
        FROM ids
        JOIN chemistry.reactions rx ON rx.id = ids.reaction_id
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id = rx.id
        LEFT JOIN ord.reaction o ON o.id = lm.ord_reaction_id
        LEFT JOIN ord.reaction_provenance rp ON rp.reaction_id = o.id
        LEFT JOIN ord.dataset d ON d.id = o.dataset_id
        LEFT JOIN LATERAL (
          SELECT s.id,s.doi,s.patent
          FROM community.reaction_submissions s
          WHERE s.reaction_id=rx.id AND s.status='accepted'
          ORDER BY s.reviewed_at DESC NULLS LAST,s.id DESC LIMIT 1
        ) cs ON true
        ORDER BY rx.id, rp.id
    """), params)).fetchall()
    return total, [
        {
            "id": row[0], "reaction_smiles": row[1], "doi": row[2],
            "patent": row[3], "dataset_name": row[4],
            "matched_roles": row[5] or [],
        }
        for row in rows
    ]


async def reaction_lookup(db: Any, query: str, limit: int) -> list[dict[str, Any]]:
    """Resolve stable reaction identities; chemical structures are searched as chemicals."""
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": min(limit, 20)}
    prefix, sep, raw_value = query.partition(":")
    value = raw_value.strip() if sep else query
    normalized_prefix = prefix.strip().lower() if sep else ""

    if normalized_prefix in {"reaction", "rxn"} and value.isdigit():
        clauses.append("rx.id=:reaction_id")
        params["reaction_id"] = int(value)
    elif normalized_prefix == "ord" and value:
        clauses.append("o.reaction_id=:source_id")
        params["source_id"] = value if value.lower().startswith("ord-") else f"ord-{value}"
    elif normalized_prefix == "doi" and value:
        clauses.append("rp.doi=:doi")
        params["doi"] = value
    elif query.isdigit():
        clauses.append("rx.id=:reaction_id")
        params["reaction_id"] = int(query)
    elif query.lower().startswith("ord-"):
        clauses.append("o.reaction_id=:source_id")
        params["source_id"] = query
    elif query.lower().startswith("10.") and "/" in query:
        clauses.append("rp.doi=:doi")
        params["doi"] = query
    if not clauses:
        return []

    rows = (await db.execute(text(f"""
        SELECT DISTINCT ON (rx.id)
          rx.id,rx.reaction_smiles,o.reaction_id,d.name,rp.doi,rp.patent,
          CASE
            WHEN rx.id=:reaction_id_hint THEN 'reaction_id'
            WHEN lower(coalesce(o.reaction_id,''))=lower(:source_id_hint) THEN 'ord_id'
            ELSE 'doi'
          END AS match_basis
        FROM chemistry.reactions rx
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id=rx.id
        LEFT JOIN ord.reaction o ON o.id=lm.ord_reaction_id
        LEFT JOIN ord.dataset d ON d.id=o.dataset_id
        LEFT JOIN ord.reaction_provenance rp ON rp.reaction_id=o.id
        WHERE {' OR '.join(clauses)}
        ORDER BY rx.id,rp.id
        LIMIT :limit
    """), {
        **params,
        "reaction_id_hint": params.get("reaction_id", -1),
        "source_id_hint": params.get("source_id", ""),
    })).fetchall()
    return [
        {
            "id": row[0], "reaction_smiles": row[1], "ord_id": row[2],
            "dataset_name": row[3], "doi": row[4], "patent": row[5],
            "match_basis": row[6],
        }
        for row in rows
    ]


@router.get("/stats")
async def stats(db=Depends(get_db)):
    cached = await cache_get("v3:stats:exact")
    if cached:
        return cached
    row = (await db.execute(text("""
        SELECT
          (SELECT exact_count FROM chemistry.statistics WHERE metric='chemicals'),
          (SELECT exact_count FROM chemistry.statistics WHERE metric='reactions'),
          (SELECT count(*) FROM ord.dataset),
          (SELECT count(*) FROM ingest.reaction_rdkit_failures)
    """))).one()
    data = {
        "chemicals": max(row[0], 0), "reactions": max(row[1], 0),
        "datasets": row[2], "rdkit_failures": row[3],
    }
    await cache_set("v3:stats:exact", data, ttl=3600)
    return data


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=4000),
    mode: str = Query("exact", pattern="^(exact|substructure|similarity)$"),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    """One entry point for names, external identifiers, SMILES and structures."""
    query = q.strip()
    cache_key = f"v4:unified-search:{mode}:{page_size}:{query}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    canonical = canonicalize_smiles(query)
    chemicals: list[dict[str, Any]] = []
    limit = min(page_size, 30)
    try:
        if mode == "substructure":
            if not canonical:
                raise HTTPException(400, "无法识别该 SMILES/SMARTS 结构")
            await db.execute(text("SET LOCAL statement_timeout = '30s'"))
            chemicals = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT}
                FROM chemistry.chemicals c
                WHERE c.mol @> mol_from_smiles(:smiles)
                LIMIT :limit
            """, {"smiles": canonical, "limit": limit})
            # A database-side ORDER BY id makes PostgreSQL scan the 124M-row
            # primary key and apply the RDKit predicate row by row. Keep the
            # GiST index scan bounded, then order the small response in memory.
            chemicals.sort(key=lambda item: item["id"])
        elif mode == "similarity":
            if not canonical:
                raise HTTPException(400, "无法识别该 SMILES 结构")
            await db.execute(text("SET LOCAL statement_timeout = '30s'"))
            chemicals = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT},
                       1 - (c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles)))
                FROM chemistry.chemicals c
                WHERE c.mol IS NOT NULL
                ORDER BY c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles))
                LIMIT :limit
            """, {"smiles": canonical, "limit": limit})
            chemicals.sort(key=lambda item: item.get("similarity") or 0, reverse=True)
        else:
            clauses: list[str] = []
            params: dict[str, Any] = {"q": query, "uq": query.upper(), "limit": limit}
            prefix, sep, raw_value = query.partition(":")
            if sep and prefix.lower() in IDENTIFIER_ARRAYS:
                clauses.append(f"c.{IDENTIFIER_ARRAYS[prefix.lower()]} @> ARRAY[:qv]")
                params["qv"] = raw_value.strip()
            elif sep and prefix.lower() == "cid" and raw_value.strip().isdigit():
                clauses.append("c.pubchem_cid = :number")
                params["number"] = int(raw_value)
            elif sep and prefix.lower() == "id" and raw_value.strip().isdigit():
                clauses.append("c.id = :number")
                params["number"] = int(raw_value)
            else:
                if query.isdigit():
                    clauses.extend(["c.id = :number", "c.pubchem_cid = :number"])
                    params["number"] = int(query)
                if CAS_RE.fullmatch(query):
                    clauses.append("c.cas_numbers @> ARRAY[:q]")
                elif INCHIKEY_RE.fullmatch(query.upper()):
                    clauses.append("c.inchikey = :uq")
                elif DTXSID_RE.fullmatch(query):
                    clauses.append("upper(c.dtxsid) = :uq")
                elif query.upper().startswith("CHEMBL"):
                    clauses.append("c.chembl_ids @> ARRAY[:q]")
                elif query.upper().startswith("CHEBI:"):
                    clauses.append("c.chebi_ids @> ARRAY[:q]")
                elif canonical:
                    # The exact-SMILES btree is intentionally partial; repeat its
                    # predicate so PostgreSQL can use it instead of scanning 124M rows.
                    clauses.append("(c.smiles = :smiles AND c.mol IS NOT NULL)")
                    params["smiles"] = canonical
            if clauses:
                chemicals = await fetch_chemicals(db, f"""
                    SELECT {CHEMICAL_SELECT}
                    FROM chemistry.chemicals c
                    WHERE {' OR '.join(clauses)}
                    ORDER BY c.id LIMIT :limit
                """, params)
            if not chemicals and not canonical and len(query) >= 2:
                # Keep the two trigram indexes independent. A cross-column OR on
                # 124M rows is both slower and less predictable than two bounded scans.
                chemicals = await fetch_chemicals(db, f"""
                    SELECT {CHEMICAL_SELECT}
                    FROM chemistry.chemicals c
                    WHERE c.preferred_name ILIKE '%' || :q || '%'
                    LIMIT :limit
                """, {"q": query, "limit": limit})
                if len(chemicals) < limit:
                    secondary = await fetch_chemicals(db, f"""
                        SELECT {CHEMICAL_SELECT}
                        FROM chemistry.chemicals c
                        WHERE c.iupac_name ILIKE '%' || :q || '%'
                        LIMIT :limit
                    """, {"q": query, "limit": limit})
                    seen = {item["id"] for item in chemicals}
                    chemicals.extend(item for item in secondary if item["id"] not in seen)
                    chemicals = chemicals[:limit]
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, "查询超时，请使用更精确的名称、标识符或结构") from exc

    reactions = await reaction_lookup(db, query, page_size) if mode == "exact" else []
    data: dict[str, Any] = {
        "query": query, "mode": mode, "canonical_smiles": canonical,
        "chemicals": chemicals, "reactions": reactions, "page_size": page_size,
    }
    await cache_set(cache_key, data, ttl=600)
    return data


@router.get("/chemicals/{chemical_id}")
async def chemical_detail(
    request: Request,
    chemical_id: int,
    enrich: str = Query("core", pattern="^(core|full)$"),
    db=Depends(get_db),
):
    rows = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c WHERE c.id=:id
    """, {"id": chemical_id})
    if not rows:
        raise HTTPException(404, "化合物不存在")
    result = rows[0]
    synonym_row = (await db.execute(text("""
        WITH source AS (
            SELECT CASE WHEN jsonb_typeof(synonyms)='array'
                THEN synonyms ELSE '[]'::jsonb END AS items
            FROM chemistry.chemicals WHERE id=:id
        )
        SELECT jsonb_array_length(items),coalesce((
            SELECT jsonb_agg(value ORDER BY ordinality)
            FROM jsonb_array_elements_text(items) WITH ORDINALITY AS alias(value,ordinality)
            WHERE ordinality<=20
        ),'[]'::jsonb)
        FROM source
    """), {"id": chemical_id})).fetchone()
    result["synonym_count"] = int(synonym_row[0]) if synonym_row else 0
    result["synonyms"] = list(synonym_row[1] or []) if synonym_row else []
    result["reaction_count"] = (await db.execute(text("""
        SELECT count(DISTINCT reaction_id) FROM chemistry.reaction_chemicals
        WHERE chemical_id=:id
    """), {"id": chemical_id})).scalar() or 0
    details, job_id, needs_refresh = await enqueue_chemical_if_needed(
        db,
        chemical_id,
        sections=FULL_DETAILS_SECTIONS if enrich == "full" else DEFAULT_SECTIONS,
        priority=80,
        request=request,
    )
    if job_id is not None:
        await db.commit()
    result["details"] = details
    result["enrichment"] = {
        "status": "queued" if job_id is not None else (
            "rate_limited" if needs_refresh else "current"
        ),
        "job_id": job_id,
        "requested_sections": list(
            FULL_DETAILS_SECTIONS if enrich == "full" else DEFAULT_SECTIONS
        ),
    }
    return result


@router.get("/chemicals/{chemical_id}/synonyms")
async def chemical_synonyms(
    chemical_id: int,
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(100, ge=1, le=500),
    db=Depends(get_db),
):
    offset = (page - 1) * page_size
    row = (await db.execute(text("""
        WITH source AS (
            SELECT CASE WHEN jsonb_typeof(synonyms)='array'
                THEN synonyms ELSE '[]'::jsonb END AS values
            FROM chemistry.chemicals WHERE id=:chemical_id
        )
        SELECT jsonb_array_length(values),coalesce((
            SELECT jsonb_agg(value ORDER BY ordinality)
            FROM jsonb_array_elements_text(values) WITH ORDINALITY AS alias(value,ordinality)
            WHERE ordinality>:offset AND ordinality<=:offset+:page_size
        ),'[]'::jsonb)
        FROM source
    """), {
        "chemical_id": chemical_id,
        "offset": offset,
        "page_size": page_size,
    })).fetchone()
    if not row:
        raise HTTPException(404, "化合物不存在")
    return {
        "chemical_id": chemical_id,
        "total": int(row[0]),
        "page": page,
        "page_size": page_size,
        "synonyms": list(row[1] or []),
    }


@router.get("/chemicals/{chemical_id}/reactions")
async def chemical_reactions(
    chemical_id: int,
    role: str = Query("any", pattern="^(any|reactant|reagent|solvent|catalyst|product)$"),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    total, items = await reaction_summaries(db, [chemical_id], role, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "reactions": items}


@router.get("/chemicals/{chemical_id}/substructure")
async def chemical_substructure(
    chemical_id: int, limit: int = Query(20, ge=1, le=50), db=Depends(get_db)
):
    smiles = (await db.execute(text(
        "SELECT smiles FROM chemistry.chemicals WHERE id=:id AND mol IS NOT NULL"
    ), {"id": chemical_id})).scalar()
    if not smiles:
        raise HTTPException(404, "化合物没有可检索结构")
    await db.execute(text("SET LOCAL statement_timeout = '30s'"))
    items = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT}
        FROM chemistry.chemicals c
        WHERE c.mol @> mol_from_smiles(:smiles) AND c.id<>:id
        LIMIT :limit
    """, {"id": chemical_id, "smiles": smiles, "limit": limit})
    # Preserve the RDKit GiST plan; see the same rule in the public search.
    items.sort(key=lambda item: item["id"])
    return {"chemicals": items}


@router.get("/chemicals/{chemical_id}/similarity")
async def chemical_similarity(
    chemical_id: int,
    threshold: float = Query(0.7, ge=0.4, le=1.0),
    limit: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    smiles = (await db.execute(text(
        "SELECT smiles FROM chemistry.chemicals WHERE id=:id AND mol IS NOT NULL"
    ), {"id": chemical_id})).scalar()
    if not smiles:
        raise HTTPException(404, "化合物没有可检索结构")
    await db.execute(text("SET LOCAL statement_timeout = '30s'"))
    items = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT},
               1 - (c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles)))
        FROM chemistry.chemicals c
        WHERE c.mol IS NOT NULL AND c.id<>:id
        ORDER BY c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles))
        LIMIT :limit
    """, {"id": chemical_id, "smiles": smiles, "limit": limit})
    items = [item for item in items if (item.get("similarity") or 0) >= threshold]
    return {"threshold": threshold, "chemicals": items}


@router.get("/reactions/{reaction_id}")
async def reaction_detail(reaction_id: int, db=Depends(get_db)):
    base = (await db.execute(text("""
        SELECT rx.id, rx.reaction_smiles, o.id, o.reaction_id,
               CASE WHEN o.id IS NULL AND cs.id IS NOT NULL THEN '社区审核' ELSE d.name END,
               COALESCE(NULLIF(cs.doi,''),rp.doi),
               COALESCE(NULLIF(cs.patent,''),rp.patent),
               COALESCE(NULLIF(cs.source_url,''),rp.publication_url),
               COALESCE(NULLIF(cs.procedure_details,''),rn.procedure_details),
               COALESCE(NULLIF(cs.safety_notes,''),rn.safety_notes),
               cond.reflux,COALESCE(cs.ph,cond.ph),
               COALESCE(NULLIF(cs.conditions_detail,''),cond.details),
               cs.temperature_value,cs.temperature_unit,
               cs.duration_value,cs.duration_unit,cs.atmosphere,
               cs.pressure_value,cs.pressure_unit,cs.id
        FROM chemistry.reactions rx
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id=rx.id
        LEFT JOIN ord.reaction o ON o.id=lm.ord_reaction_id
        LEFT JOIN ord.dataset d ON d.id=o.dataset_id
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_provenance p WHERE p.reaction_id=o.id ORDER BY p.id LIMIT 1) rp ON true
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_notes n WHERE n.reaction_id=o.id ORDER BY n.id LIMIT 1) rn ON true
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_conditions c WHERE c.reaction_id=o.id ORDER BY c.id LIMIT 1) cond ON true
        LEFT JOIN LATERAL (
          SELECT * FROM community.reaction_submissions s
          WHERE s.reaction_id=rx.id AND s.status='accepted'
          ORDER BY s.reviewed_at DESC NULLS LAST,s.id DESC LIMIT 1
        ) cs ON true
        WHERE rx.id=:id
    """), {"id": reaction_id})).fetchone()
    if not base:
        raise HTTPException(404, "反应不存在")

    participants = (await db.execute(text(f"""
        SELECT {CHEMICAL_SELECT}, rc.role, rc.occurrence_count
        FROM chemistry.reaction_chemicals rc
        JOIN chemistry.chemicals c ON c.id=rc.chemical_id
        WHERE rc.reaction_id=:id
        ORDER BY CASE rc.role WHEN 'REACTANT' THEN 1 WHEN 'REAGENT' THEN 2
                 WHEN 'CATALYST' THEN 3 WHEN 'SOLVENT' THEN 4 WHEN 'PRODUCT' THEN 5 ELSE 6 END,
                 c.id
    """), {"id": reaction_id})).fetchall()
    compounds = []
    for row in participants:
        item = chemical_dict(row)
        item.update(role=row[17], occurrence_count=row[18])
        compounds.append(item)

    temperature = (await db.execute(text("""
        SELECT t.value, t.units::text
        FROM ord.reaction_map lm
        JOIN ord.reaction_conditions rc ON rc.reaction_id=lm.ord_reaction_id
        JOIN ord.temperature_conditions tc ON tc.reaction_conditions_id=rc.id
        JOIN ord.temperature t ON t.temperature_conditions_id=tc.id
        WHERE lm.reaction_id=:id AND t.value IS NOT NULL ORDER BY t.id LIMIT 1
    """), {"id": reaction_id})).fetchone()
    workup = (await db.execute(text("""
        SELECT rw.type::text, rw.details, rw.keep_phase, rw.target_ph
        FROM ord.reaction_map lm
        JOIN ord.reaction_workup rw ON rw.reaction_id=lm.ord_reaction_id
        WHERE lm.reaction_id=:id ORDER BY rw.id
    """), {"id": reaction_id})).fetchall()
    yields = (await db.execute(text("""
        SELECT pc.chemical_id, max(p.value)
        FROM ord.reaction_map lm
        JOIN ord.reaction_outcome ro ON ro.reaction_id=lm.ord_reaction_id
        JOIN ord.product_compound pc ON pc.reaction_outcome_id=ro.id
        JOIN ord.product_measurement pm ON pm.product_compound_id=pc.id AND pm.type='YIELD'
        JOIN ord.percentage p ON p.product_measurement_id=pm.id
        WHERE lm.reaction_id=:id AND pc.chemical_id IS NOT NULL
        GROUP BY pc.chemical_id
    """), {"id": reaction_id})).fetchall()
    yield_map = {row[0]: round(float(row[1]), 3) for row in yields}
    community_yields = (await db.execute(text("""
        WITH latest AS (
          SELECT id FROM community.reaction_submissions
          WHERE reaction_id=:id AND status='accepted'
          ORDER BY reviewed_at DESC NULLS LAST,id DESC LIMIT 1
        )
        SELECT p.chemical_id,max(p.yield_percent)
        FROM latest
        JOIN community.reaction_submission_participants p ON p.submission_id=latest.id
        WHERE p.role='PRODUCT' AND p.chemical_id IS NOT NULL
          AND p.yield_percent IS NOT NULL
        GROUP BY p.chemical_id
    """), {"id": reaction_id})).fetchall()
    yield_map.update({row[0]: round(float(row[1]), 3) for row in community_yields})
    for item in compounds:
        if item["role"] == "PRODUCT":
            item["yield_percent"] = yield_map.get(item["id"])

    conditions_detail = base[12]
    if conditions_detail and conditions_detail.strip().lower().startswith("see reaction.notes"):
        conditions_detail = None

    return {
        "id": base[0], "reaction_smiles": base[1], "ord_record_id": base[2],
        "ord_id": base[3], "dataset_name": base[4], "doi": base[5],
        "patent": base[6], "publication_url": base[7],
        "procedure_details": base[8], "safety_notes": base[9],
        "reflux": base[10], "ph": base[11], "conditions_detail": conditions_detail,
        "temperature": (
            {"value": base[13], "unit": base[14]} if base[13] is not None
            else ({"value": temperature[0], "unit": temperature[1]} if temperature else None)
        ),
        "duration": ({"value": base[15], "unit": base[16]} if base[15] is not None else None),
        "atmosphere": base[17],
        "pressure": ({"value": base[18], "unit": base[19]} if base[18] is not None else None),
        "community_submission_id": base[20],
        "participants": compounds,
        "workup": [
            {"type": row[0], "details": row[1], "keep_phase": row[2], "target_ph": row[3]}
            for row in workup
        ],
    }


@router.get("/datasets")
async def datasets(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50), db=Depends(get_db)
):
    rows = (await db.execute(text("""
        SELECT id, dataset_id, name, description, num_reactions, submitted_at
        FROM ord.dataset ORDER BY num_reactions DESC NULLS LAST, id
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": (page - 1) * page_size})).fetchall()
    return [{
        "id": row[0], "dataset_id": row[1], "name": row[2], "description": row[3],
        "reaction_count": row[4], "submitted_at": row[5],
    } for row in rows]
