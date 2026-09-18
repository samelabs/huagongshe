"""反应详情查询/拼装服务层 — 自 api/routes.py 下沉, 逻辑零改动(批次5a)。

外部引用者: routes.reaction_detail, mcp_server(get_reaction 经 routes)。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from rdkit.Chem import rdChemReactions
from sqlalchemy import text

from ..chemistry import canonicalize_smiles
from ..core.rate_limit import enforce
from ..schemas.reactions import ReactionBody

from .chemicals import CHEMICAL_SELECT, attach_localized_names, chemical_dict, clean_float


async def load_reaction_detail(
    db: Any, reaction_id: int, viewer_id: int, viewer_is_admin: bool
) -> dict[str, Any] | None:
    """反应详情(可见性内嵌 WHERE); None=不存在或不可见(调用方转 404)。"""
    base = (await db.execute(text("""
        SELECT rx.id,rx.reaction_smiles,rx.visibility,rx.moderation_status,
               rx.created_by_user_id,rx.created_at,rx.updated_at,
               COALESCE(NULLIF(rx.procedure_details,''),rn.procedure_details),
               COALESCE(NULLIF(rx.safety_notes,''),rn.safety_notes),
               COALESCE(rx.ph,cond.ph),COALESCE(NULLIF(rx.conditions_detail,''),cond.details),
               rx.temperature_value,rx.temperature_unit,rx.duration_value,rx.duration_unit,
               rx.atmosphere,rx.pressure_value,rx.pressure_unit,rx.workup_details,
               rx.source_type,COALESCE(NULLIF(rx.doi,''),rp.doi),
               COALESCE(NULLIF(rx.patent,''),rp.patent),
               COALESCE(NULLIF(rx.source_url,''),rp.publication_url),
               CASE WHEN rx.created_by_user_id IS NOT NULL
                    THEN rx.source_citation ELSE d.name END,
               rx.note,o.id,o.reaction_id,cond.reflux,
               u.username,u.display_name,u.avatar_path,
               (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=rx.id),
               EXISTS(SELECT 1 FROM community.reaction_follows
                      WHERE reaction_id=rx.id AND user_id=:viewer_id)
        FROM chemistry.reactions rx
        LEFT JOIN community.users u ON u.id=rx.created_by_user_id
        LEFT JOIN ord.reaction_map lm ON lm.reaction_id=rx.id
        LEFT JOIN ord.reaction o ON o.id=lm.ord_reaction_id
        LEFT JOIN ord.dataset d ON d.id=o.dataset_id
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_provenance p WHERE p.reaction_id=o.id ORDER BY p.id LIMIT 1) rp ON true
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_notes n WHERE n.reaction_id=o.id ORDER BY n.id LIMIT 1) rn ON true
        LEFT JOIN LATERAL (SELECT * FROM ord.reaction_conditions c WHERE c.reaction_id=o.id ORDER BY c.id LIMIT 1) cond ON true
        WHERE rx.id=:id
          AND (:is_admin OR rx.created_by_user_id=:viewer_id
               OR (rx.visibility='public' AND rx.moderation_status='visible'))
    """), {"id": reaction_id, "viewer_id": viewer_id, "is_admin": viewer_is_admin})).fetchone()
    if not base:
        return None

    participants = (await db.execute(text(f"""
        SELECT {CHEMICAL_SELECT}, rc.role,rc.occurrence_count,rc.amount_value,rc.amount_unit,
               rc.equivalents,rc.concentration_value,rc.concentration_unit,rc.yield_percent
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
        item.update(
            role=row[17],occurrence_count=row[18],amount_value=row[19],amount_unit=row[20],
            equivalents=row[21],concentration_value=row[22],concentration_unit=row[23],
            yield_percent=clean_float(row[24]),
        )
        compounds.append(item)
    await attach_localized_names(db, compounds)

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
    yield_map = {row[0]: clean_float(row[1], round_digits=3) for row in yields}
    for item in compounds:
        if item["role"] == "PRODUCT" and item["yield_percent"] is None:
            item["yield_percent"] = yield_map.get(item["id"])

    conditions_detail = base[10]
    if conditions_detail and conditions_detail.strip().lower().startswith("see reaction.notes"):
        conditions_detail = None

    temp_value = clean_float(base[11])
    temp_unit = base[12]
    if temp_value is None and temperature:
        temp_value = clean_float(temperature[0])
        temp_unit = temperature[1]
    temperature_out = (
        {"value": temp_value, "unit": temp_unit}
        if temp_value is not None
        else None
    )

    return {
        "id": base[0], "reaction_smiles": base[1], "visibility": base[2],
        "moderation_status": base[3], "created_at": base[5], "updated_at": base[6],
        "ord_record_id": base[25], "ord_id": base[26], "dataset_name": base[23],
        "source_type": base[19], "doi": base[20], "patent": base[21],
        "publication_url": base[22], "source_citation": base[23],
        "procedure_details": base[7], "safety_notes": base[8],
        "reflux": base[27], "ph": base[9], "conditions_detail": conditions_detail,
        "temperature": temperature_out,
        "duration": ({"value": base[13], "unit": base[14]} if base[13] is not None else None),
        "atmosphere": base[15],
        "pressure": ({"value": base[16], "unit": base[17]} if base[16] is not None else None),
        "workup_details": base[18], "note": base[24],
        "creator": ({"username": base[28], "display_name": base[29], "avatar_url": base[30]}
                    if base[28] else None),
        "is_owner": base[4] == viewer_id and base[4] is not None,
        "follower_count": int(base[31]), "is_following": bool(base[32]),
        "participants": compounds,
        "workup": [
            {"type": row[0], "details": row[1], "keep_phase": row[2], "target_ph": row[3]}
            for row in workup
        ],
    }



async def list_my_reactions(
    db, *,
    actor_id: int,
    visibility: str,
    page: int,
    page_size: int,
) -> dict:
    """我的反应列表(G2.5C 自 api/reactions.py::my_reactions 下沉)。

    transport-neutral: 只消费 adapter 已 validated/clamp 的
    visibility/page/page_size; offset 计算属 shared query semantics。
    bounded UNION ALL SQL 是硬 contract(防 2.4M 行 PK 反向扫), 逐字迁移;
    counts 只统计当前 actor 自己的全量 reactions(不受 visibility/page 影响)。
    无记录 → 正常 empty items(无业务 not-found error)。
    """
    offset = (page - 1) * page_size
    params = {
        "user_id": actor_id, "visibility": visibility, "limit": page_size,
        "offset": offset, "window": offset + page_size,
    }
    if visibility == "all":
        # Keep each branch on (created_by_user_id, visibility, id DESC). Without
        # these bounded branches PostgreSQL may walk the 2.4M-row primary key
        # backwards to satisfy ORDER BY before it applies the owner filter.
        query = text("""
            WITH owned AS MATERIALIZED (
              (SELECT id,reaction_smiles,visibility,moderation_status,created_at,updated_at
               FROM chemistry.reactions
               WHERE created_by_user_id=:user_id AND visibility='public'
               ORDER BY id DESC LIMIT :window)
              UNION ALL
              (SELECT id,reaction_smiles,visibility,moderation_status,created_at,updated_at
               FROM chemistry.reactions
               WHERE created_by_user_id=:user_id AND visibility='private'
               ORDER BY id DESC LIMIT :window)
            )
            SELECT r.*,
              (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=r.id) AS followers
            FROM owned r ORDER BY id DESC LIMIT :limit OFFSET :offset
        """)
    else:
        query = text("""
            SELECT r.id,r.reaction_smiles,r.visibility,r.moderation_status,r.created_at,r.updated_at,
              (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=r.id) AS followers
            FROM chemistry.reactions r
            WHERE r.created_by_user_id=:user_id AND r.visibility=:visibility
            ORDER BY r.id DESC LIMIT :limit OFFSET :offset
        """)
    rows = (await db.execute(query, params)).mappings().all()
    count_rows = (await db.execute(text("""
        SELECT visibility,count(*)
        FROM chemistry.reactions
        WHERE created_by_user_id=:user_id
        GROUP BY visibility
    """), {"user_id": actor_id})).all()
    counts = {"public": 0, "private": 0}
    for value, count in count_rows:
        counts[value] = int(count)
    return {
        "items": [dict(row) for row in rows], "counts": {**counts, "all": sum(counts.values())},
        "page": page, "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# G3.1B — canonical validation kernel + shared validate orchestration
# (自 api/reactions.py 下沉; PURE COMPUTATION, RDKit only, 零 DB/事务副作用)
# ---------------------------------------------------------------------------

class ReactionValidationError(Exception):
    """反应草稿校验失败的 neutral 语义错误。

    kind ∈ {INVALID_STRUCTURE, DUPLICATE_PARTICIPANT, INVALID_REACTION};
    只携带 kind + detail(原文), 不含传输层 status/headers。
    Web adapter: INVALID_STRUCTURE→400 / DUPLICATE_PARTICIPANT→409 /
    INVALID_REACTION→400; MCP adapter: 工具报错(detail)。
    """

    INVALID_STRUCTURE = "invalid_structure"
    DUPLICATE_PARTICIPANT = "duplicate_participant"
    INVALID_REACTION = "invalid_reaction"

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def canonical_participants(
    body: ReactionBody,
) -> tuple[list[dict[str, Any]], str]:
    """唯一 canonical 参与物/反应表达式校验 kernel(原实现逐字迁移)。

    原传输层异常语义 → ReactionValidationError(kind):
      无法解析参与物结构   → INVALID_STRUCTURE   (原 400)
      同一化合物+角色重复  → DUPLICATE_PARTICIPANT (原 409)
      RDKit 反应结构解析   → INVALID_REACTION     (原 400)
    """
    participants: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    grouped: dict[str, list[str]] = defaultdict(list)
    for position, item in enumerate(body.participants):
        canonical = canonicalize_smiles(item.smiles)
        if not canonical:
            raise ReactionValidationError(
                ReactionValidationError.INVALID_STRUCTURE,
                f"无法解析参与物结构：{item.smiles[:80]}")
        key = (item.role, canonical)
        if key in seen:
            raise ReactionValidationError(
                ReactionValidationError.DUPLICATE_PARTICIPANT,
                "同一化合物和角色请合并为一项，并填写出现次数")
        seen.add(key)
        record = {"position": position, "canonical_smiles": canonical, **item.model_dump(exclude={"smiles"})}
        participants.append(record)
        grouped[item.role].extend([canonical] * item.occurrence_count)
    reaction_smiles = ".".join(grouped["REACTANT"]) + ">" + ".".join(
        value for role in ("REAGENT", "CATALYST", "SOLVENT") for value in grouped[role]
    ) + ">" + ".".join(grouped["PRODUCT"])
    try:
        reaction = rdChemReactions.ReactionFromSmarts(reaction_smiles, useSmiles=True)
    except Exception as exc:
        raise ReactionValidationError(
            ReactionValidationError.INVALID_REACTION,
            "反应结构无法通过 RDKit 解析") from exc
    if reaction is None or not reaction.GetNumReactantTemplates() or not reaction.GetNumProductTemplates():
        raise ReactionValidationError(
            ReactionValidationError.INVALID_REACTION,
            "反应结构无法通过 RDKit 解析")
    return participants, reaction_smiles


async def validate_reaction_draft(
    db_unused: None = None, *,
    actor_id: int,
    body: ReactionBody,
) -> dict[str, Any]:
    """shared validate orchestration(G3.1B; HTTP/MCP 共用)。

    neutral rate enforce(reaction-validate / str(actor_id) / 20 / 60)
    → to_thread(canonical kernel, CPU-bound 不回 event loop)
    → 当前 canonical response assembly。
    不负责: auth/scope/传输层异常或上下文对象。
    """
    await enforce("reaction-validate", str(actor_id), 20, 60)
    participants, reaction_smiles = await asyncio.to_thread(
        canonical_participants, body)
    return {
        "valid": True, "reaction_smiles": reaction_smiles,
        "participants": [
            {"role": item["role"], "canonical_smiles": item["canonical_smiles"],
             "occurrence_count": item["occurrence_count"]}
            for item in participants
        ],
    }
