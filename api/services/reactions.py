"""反应详情查询/拼装服务层 — 自 api/routes.py 下沉, 逻辑零改动(批次5a)。

外部引用者: routes.reaction_detail, mcp_server(get_reaction 经 routes)。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from rdkit import Chem
from rdkit.Chem import Descriptors, rdChemReactions, rdMolDescriptors
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..chemistry import canonicalize_smiles
from ..core.config import settings
from ..core.rate_limit import enforce
from ..schemas.reactions import ReactionBody

from .chemicals import CHEMICAL_SELECT, attach_localized_names, chemical_dict, clean_float

logger = logging.getLogger(__name__)


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


class MissingIdempotencyKeyError(Exception):
    """G3.1C: agent 提交缺 Idempotency-Key(原 HTTP 400 / MCP 在 adapter 前置拦截)。"""

    def __init__(self) -> None:
        super().__init__("使用 API Token 提交必须提供 Idempotency-Key")
        self.detail = "使用 API Token 提交必须提供 Idempotency-Key"


class IdempotencyKeyTooLongError(Exception):
    """G3.1C: Idempotency-Key 超 200 字符(原 HTTP 400 / MCP 工具报错同文案)。"""

    def __init__(self) -> None:
        super().__init__("Idempotency-Key 不能超过 200 个字符")
        self.detail = "Idempotency-Key 不能超过 200 个字符"


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


def chemical_properties(smiles: str) -> dict[str, Any]:
    # G3.1C: 原 adapter HTTP 400 → neutral error(kind 语义=结构不可解析)。
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ReactionValidationError(
            ReactionValidationError.INVALID_STRUCTURE,
            "化合物结构无法通过 RDKit 解析")
    try:
        inchikey = Chem.MolToInchiKey(mol) or None
    except Exception:
        inchikey = None
    return {
        "molecular_formula": rdMolDescriptors.CalcMolFormula(mol),
        "average_mass": float(Descriptors.MolWt(mol)),
        "monoisotopic_mass": float(Descriptors.ExactMolWt(mol)),
        "inchikey": inchikey,
    }


class UnresolvedIdentityError(Exception):
    """resolver 五状态中 CONFLICT/AMBIGUOUS 的 transport-neutral 表达(E9-B)。

    fail-closed: 未裁定的身份不得创建 chemical 行。调用方显式处理:
    HTTP reaction create → 409; MCP → transport 错误; search 建行 → 降级不建行。
    status/reason 携带 resolver 裁定事实(evidence 见 resolver 日志侧)。
    """

    def __init__(self, status: str, reason: str = ""):
        self.status = status
        self.reason = reason
        detail = {
            "CONFLICT": "化合物身份冲突：相同结构键对应多条互斥记录，需人工裁定，禁止自动创建",
            "AMBIGUOUS": "化合物身份不明确：存在多个候选且无结构判据，禁止自动创建",
        }.get(status, "化合物身份未裁定，禁止自动创建")
        super().__init__(detail)
        self.detail = detail


async def resolve_or_create_chemical(db, smiles: str) -> tuple[int, bool]:
    # 锁键用 canonical 形式: 同一分子的不同写法(CCO/OCC)必须落在同一把锁上,
    # 否则并发双写可各建一行(缝只开一次, 但没有必要留). 入参已是 canonical 时零开销.
    # RDKit 解析是 CPU-bound, 下沉线程池防卡事件循环(与 :50 chemical_properties 同口径).
    canonical = await asyncio.to_thread(canonicalize_smiles, smiles) or smiles
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:smiles,0))"), {"smiles": canonical})
    props = await asyncio.to_thread(chemical_properties, canonical)
    inchikey = props.get("inchikey")
    # 0906 治理机制: 定位/裁定改走 identity.resolve_chemical 五状态契约。
    # E9-B fail-closed(取代 0906 注释里的"不可能出现"假设):
    #   EXACT/EQUIVALENT → reuse; NEW → INSERT;
    #   CONFLICT(ik 命中但两行非空 CID 互斥等) / AMBIGUOUS → 禁止 INSERT,
    #   抛 UnresolvedIdentityError, 由调用方(reaction 409 / search 降级)显式处理。
    from .identity import resolve_chemical
    # create=False: NEW 时不占行 — 完整行(带mol/指纹)由本函数下方 INSERT
    # 一次性建, 避免 resolve 先建裸占位行再建完整行的双行缝(终审0906)
    res = await resolve_chemical(db, inchikey=inchikey, create=False)
    if res.chemical_id is not None and res.status in ("EQUIVALENT", "EXACT"):
        return int(res.chemical_id), False
    if res.status in ("CONFLICT", "AMBIGUOUS"):
        raise UnresolvedIdentityError(res.status, res.reason)
    chemical_id = int((await db.execute(text("""
        INSERT INTO chemistry.chemicals
          (smiles,molecular_formula,average_mass,monoisotopic_mass,inchikey,
           mol,morgan_bfp,morgan_sfp,created_at,updated_at)
        VALUES
          (:smiles,:molecular_formula,:average_mass,:monoisotopic_mass,:inchikey,
           mol_from_smiles(:smiles),morganbv_fp(mol_from_smiles(:smiles)),
           morgan_fp(mol_from_smiles(:smiles)),now(),now())
        RETURNING id
    """), {"smiles": canonical, **props})).scalar_one())
    await db.execute(text("""
        UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
        WHERE metric='chemicals'
    """))
    # §3 MVP trigger 1(§3.1 修正: 真正 best-effort):
    if inchikey:
        try:
            # §3 frozen-baseline correction: 局部 import(勿改模块级 ——
            # test_discovery_fix31 monkeypatch api.services.discovery.enqueue_discovery 注入真实 PG error, 局部 import 保持真链)
            from .discovery import enqueue_discovery
            async with db.begin_nested():
                await enqueue_discovery(
                    db, chemical_id=chemical_id, inchikey=inchikey,
                    request_context={"origin": "reaction_insert"})
        except Exception:
            logger.warning("identity discovery enqueue failed chemical_id=%s",
                           chemical_id, exc_info=True)
    return chemical_id, True


def reaction_values(body: ReactionBody) -> dict[str, Any]:
    return body.model_dump(exclude={"participants"})


async def resolve_participants(db, participants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    resolved: list[dict[str, Any]] = []
    created: list[int] = []
    for participant in participants:
        chemical_id, is_new = await resolve_or_create_chemical(db, participant["canonical_smiles"])
        resolved.append({**participant, "chemical_id": chemical_id})
        if is_new:
            created.append(chemical_id)
    return resolved, created


async def write_relationships(db, reaction_id: int, participants: list[dict[str, Any]]) -> None:
    for item in participants:
        await db.execute(text("""
            INSERT INTO chemistry.reaction_chemicals
              (reaction_id,chemical_id,role,occurrence_count,amount_value,amount_unit,
               equivalents,concentration_value,concentration_unit,yield_percent)
            VALUES
              (:reaction_id,:chemical_id,:role,:occurrence_count,:amount_value,:amount_unit,
               :equivalents,:concentration_value,:concentration_unit,:yield_percent)
        """), {"reaction_id": reaction_id, **item})


async def notify_new_reaction(db, actor_id: int, reaction_id: int) -> None:
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,reaction_id,dedupe_key)
        SELECT follower_user_id,'new_reaction',:actor_id,:reaction_id,
               'new-reaction:' || follower_user_id::text || ':' || :reaction_id_text
        FROM community.user_follows
        WHERE followed_user_id=:actor_id AND follower_user_id<>:actor_id
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "actor_id": actor_id, "reaction_id": reaction_id, "reaction_id_text": str(reaction_id),
    })


async def notify_new_reaction_safely(db, actor_id: int, reaction_id: int) -> None:
    """Keep auxiliary activity fan-out outside and below the core write budget."""
    try:
        await db.execute(text("SET LOCAL statement_timeout='1000ms'"))
        await notify_new_reaction(db, actor_id, reaction_id)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "reaction activity notification skipped",
            exc_info=True,
            extra={"actor_id": actor_id, "reaction_id": reaction_id},
        )


async def reaction_response(db, reaction_id: int, created_chemicals: list[int] | None = None) -> dict[str, Any]:
    row = (await db.execute(text("""
        SELECT id,reaction_smiles,visibility,created_by_user_id,created_via,created_at,updated_at
        FROM chemistry.reactions WHERE id=:id
    """), {"id": reaction_id})).fetchone()
    participants = (await db.execute(text("""
        SELECT chemical_id,role,occurrence_count,amount_value,amount_unit,equivalents,
               concentration_value,concentration_unit,yield_percent
        FROM chemistry.reaction_chemicals WHERE reaction_id=:id
        ORDER BY CASE role WHEN 'REACTANT' THEN 1 WHEN 'REAGENT' THEN 2 WHEN 'CATALYST' THEN 3
                           WHEN 'SOLVENT' THEN 4 ELSE 5 END,chemical_id
    """), {"id": reaction_id})).mappings().all()
    return {
        "id": row[0], "hrid": f"HRID {row[0]}", "reaction_smiles": row[1],
        "visibility": row[2], "created_by_user_id": row[3], "created_via": row[4],
        "created_at": row[5], "updated_at": row[6],
        "participants": [dict(item) for item in participants],
        "created_chemical_ids": created_chemicals or [],
        "url": f"https://huagongshe.com/reaction/{row[0]}",
    }


async def create_reaction(
    db,
    *,
    actor_id: int,
    auth_kind: str,
    body: ReactionBody,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """shared create orchestration(G3.1C; HTTP/MCP 共用)。

    共享 rate(reaction-write-minute/day, str(actor_id), settings 值, 先于 key 校验)
    → agent 缺 key 检查 → key 长度检查 → 幂等预检
    → canonical validation(to_thread) → resolve participants → INSERT
    → IntegrityError 竞态恢复 → relationships → public statistics
    → commit → post-commit notify → canonical response。
    不负责: auth/scope/传输层异常或上下文对象。
    """
    await enforce("reaction-write-minute", str(actor_id), settings.api_reaction_write_limit_per_minute, 60)
    await enforce("reaction-write-day", str(actor_id), settings.api_reaction_write_limit_per_day, 86400)
    if auth_kind == "agent" and not idempotency_key:
        raise MissingIdempotencyKeyError()
    if idempotency_key and len(idempotency_key) > 200:
        raise IdempotencyKeyTooLongError()
    if idempotency_key:
        existing = (await db.execute(text("""
            SELECT id FROM chemistry.reactions
            WHERE created_by_user_id=:user_id AND idempotency_key=:key
        """), {"user_id": actor_id, "key": idempotency_key})).scalar()
        if existing is not None:
            return await reaction_response(db, int(existing))

    try:
        participants, reaction_smiles = await asyncio.to_thread(canonical_participants, body)
    except ReactionValidationError:
        raise
    try:
        resolved, created_chemicals = await resolve_participants(db, participants)
    except UnresolvedIdentityError:
        # E9-B fail-closed: CONFLICT/AMBIGUOUS → 化学行+0, 反应+0,
        # reaction_chemicals +0, statistics 不推进, discovery 不入队。
        # resolve 阶段尚未发生任何本事务写入(INSERT 在其后), rollback
        # 清除 advisory lock/可能的 savepoint 后向上抛给 adapter 映射 409。
        await db.rollback()
        raise
    values = reaction_values(body)
    try:
        reaction_id = int((await db.execute(text("""
            INSERT INTO chemistry.reactions
              (id,reaction_smiles,reaction,created_by_user_id,visibility,created_via,
               procedure_details,conditions_detail,temperature_value,temperature_unit,
               duration_value,duration_unit,ph,atmosphere,pressure_value,pressure_unit,
               workup_details,safety_notes,source_type,doi,patent,source_url,source_citation,
               note,idempotency_key)
            VALUES
              (nextval('chemistry.reactions_id_seq'),:reaction_smiles,
               CAST(:reaction_input AS public.reaction),:user_id,:visibility,:created_via,
               :procedure_details,:conditions_detail,:temperature_value,:temperature_unit,
               :duration_value,:duration_unit,:ph,:atmosphere,:pressure_value,:pressure_unit,
               :workup_details,:safety_notes,:source_type,:doi,:patent,:source_url,:source_citation,
               :note,:idempotency_key)
            RETURNING id
        """), {
            **values, "reaction_smiles": reaction_smiles, "reaction_input": reaction_smiles,
            "user_id": actor_id, "created_via": "agent" if auth_kind == "agent" else "web",
            "idempotency_key": idempotency_key,
        })).scalar_one())
    except IntegrityError:
        await db.rollback()
        if idempotency_key:
            existing = (await db.execute(text("""
                SELECT id FROM chemistry.reactions
                WHERE created_by_user_id=:user_id AND idempotency_key=:key
            """), {"user_id": actor_id, "key": idempotency_key})).scalar()
            if existing is not None:
                return await reaction_response(db, int(existing))
        raise
    await write_relationships(db, reaction_id, resolved)
    if body.visibility == "public":
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
            WHERE metric='reactions'
        """))
    await db.commit()
    if body.visibility == "public":
        await notify_new_reaction_safely(db, actor_id, reaction_id)
    return await reaction_response(db, reaction_id, created_chemicals)


# ---------------------------------------------------------------------------
# E3 — reaction update/delete application ownership
# (自 api/reactions.py 逐字下沉; adapter 只余 auth + neutral → HTTP 映射)
# ---------------------------------------------------------------------------

class AgentReactionMutationForbiddenError(Exception):
    """agent(AI Key)不开放反应编辑/删除的 neutral 错误。

    原 adapter 403 文案逐字保留(编辑/删除两条不同 detail);
    不含传输层 status/headers。
    """

    EDIT_DETAIL = "API Token 当前不开放反应编辑，请使用网页登录会话"
    DELETE_DETAIL = "API Token 当前不开放反应删除，请使用网页登录会话"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ReactionAccessError(Exception):
    """update/delete 的存在性/所有权 neutral 错误(不含传输层 status)。

    kind → 迁移前 HTTP 语义(逐条保留, 不合并文案):
      NOT_FOUND        → 404 反应不存在
      NOT_OWNER        → 403 只能维护自己创建的反应      (update 非 owner)
      SYSTEM_IMPORT    → 403 系统导入反应不能由用户删除  (delete created_by_user_id IS NULL)
      DELETE_NOT_OWNER → 403 只能删除自己创建的反应      (delete 非 owner)
    """

    NOT_FOUND = "not_found"
    NOT_OWNER = "not_owner"
    SYSTEM_IMPORT = "system_import"
    DELETE_NOT_OWNER = "delete_not_owner"

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


async def update_reaction(
    db,
    *,
    actor_id: int,
    auth_kind: str,
    reaction_id: int,
    body: ReactionBody,
) -> dict[str, Any]:
    """reaction PUT 的唯一业务 owner(E3; 原 api/reactions.py 逐字迁移)。

    顺序(与迁移前逐条一致): agent 403 → rate(reaction-write-minute)
    → row lock(FOR UPDATE) → 存在性/owner 检查 → canonical kernel(to_thread)
    → resolve participants → UPDATE row → 关系替换 → visibility/follows/statistics
    → commit → post-commit notify → canonical response。
    事务边界(行锁/全部 DB mutation/commit/rollback)由本函数自持, adapter
    零事务片段。不负责 auth/scope/传输层异常或响应映射。
    """
    if auth_kind == "agent":
        raise AgentReactionMutationForbiddenError(
            AgentReactionMutationForbiddenError.EDIT_DETAIL)
    await enforce("reaction-write-minute", str(actor_id), settings.api_reaction_write_limit_per_minute, 60)
    try:
        current = (await db.execute(text("""
            SELECT created_by_user_id,visibility,moderation_status
            FROM chemistry.reactions WHERE id=:id FOR UPDATE
        """), {"id": reaction_id})).fetchone()
        if not current:
            raise ReactionAccessError(ReactionAccessError.NOT_FOUND, "反应不存在")
        if current[0] != actor_id:
            raise ReactionAccessError(ReactionAccessError.NOT_OWNER, "只能维护自己创建的反应")
        participants, reaction_smiles = await asyncio.to_thread(canonical_participants, body)
        try:
            resolved, created_chemicals = await resolve_participants(db, participants)
        except UnresolvedIdentityError:
            # E9-B fail-closed(与 create 同口径): FOR UPDATE 行锁随 rollback 释放,
            # 未发生任何参与者/行写入。
            await db.rollback()
            raise
        values = reaction_values(body)
        await db.execute(text("""
            UPDATE chemistry.reactions SET
              reaction_smiles=:reaction_smiles,reaction=CAST(:reaction_input AS public.reaction),
              visibility=:visibility,procedure_details=:procedure_details,
              conditions_detail=:conditions_detail,temperature_value=:temperature_value,
              temperature_unit=:temperature_unit,duration_value=:duration_value,
              duration_unit=:duration_unit,ph=:ph,atmosphere=:atmosphere,
              pressure_value=:pressure_value,pressure_unit=:pressure_unit,
              workup_details=:workup_details,safety_notes=:safety_notes,source_type=:source_type,
              doi=:doi,patent=:patent,source_url=:source_url,source_citation=:source_citation,
              note=:note,updated_at=now()
            WHERE id=:id
        """), {**values, "id": reaction_id, "reaction_smiles": reaction_smiles, "reaction_input": reaction_smiles})
        await db.execute(text("DELETE FROM chemistry.reaction_chemicals WHERE reaction_id=:id"), {"id": reaction_id})
        await write_relationships(db, reaction_id, resolved)
        if body.visibility == "private":
            await db.execute(text("DELETE FROM community.reaction_follows WHERE reaction_id=:id"), {"id": reaction_id})
            if current[1] == "public" and current[2] == "visible":
                await db.execute(text("""
                    UPDATE chemistry.statistics SET exact_count=greatest(exact_count-1,0),calculated_at=now()
                    WHERE metric='reactions'
                """))
        elif current[1] == "private" and current[2] == "visible":
            await db.execute(text("""
                UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
                WHERE metric='reactions'
            """))
        await db.commit()
    except Exception:
        # E3: 显式 rollback 边界(迁移前依赖 session 关闭隐式回滚); 失败路径
        # 观测结果等价(零落库), 行锁在异常点即释放; commit 之后不再回滚。
        await db.rollback()
        raise
    if body.visibility == "public" and current[1] == "private":
        await notify_new_reaction_safely(db, actor_id, reaction_id)
    return await reaction_response(db, reaction_id, created_chemicals)


async def delete_reaction(
    db,
    *,
    actor_id: int,
    auth_kind: str,
    reaction_id: int,
) -> None:
    """reaction DELETE 的唯一业务 owner(E3; 原 api/reactions.py 逐字迁移)。

    顺序: agent 403 → row lock(FOR UPDATE) → 404 → 系统导入 403 → 非 owner 403
    → DELETE row(reaction_chemicals / reaction_follows 走 FK CASCADE)
    → public+visible statistics -1 → commit。
    delete 无 rate 限制(迁移前后一致, 未新增)。事务边界由本函数自持。
    """
    if auth_kind == "agent":
        raise AgentReactionMutationForbiddenError(
            AgentReactionMutationForbiddenError.DELETE_DETAIL)
    try:
        record = (await db.execute(text("""
            SELECT created_by_user_id,visibility,moderation_status
            FROM chemistry.reactions WHERE id=:id FOR UPDATE
        """), {"id": reaction_id})).fetchone()
        if record is None:
            raise ReactionAccessError(ReactionAccessError.NOT_FOUND, "反应不存在")
        owner = record[0]
        if owner is None:
            raise ReactionAccessError(ReactionAccessError.SYSTEM_IMPORT, "系统导入反应不能由用户删除")
        if int(owner) != actor_id:
            raise ReactionAccessError(ReactionAccessError.DELETE_NOT_OWNER, "只能删除自己创建的反应")
        await db.execute(text("DELETE FROM chemistry.reactions WHERE id=:id"), {"id": reaction_id})
        if record[1] == "public" and record[2] == "visible":
            await db.execute(text("""
                UPDATE chemistry.statistics SET exact_count=greatest(exact_count-1,0),calculated_at=now()
                WHERE metric='reactions'
            """))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
