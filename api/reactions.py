"""The single write path for web users and their AI Agents."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from rdkit import Chem
from rdkit.Chem import Descriptors, rdChemReactions, rdMolDescriptors
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .core.cache import cache_delete
from .chemistry import canonicalize_smiles
from .schemas.reactions import ReactionBody
from .core.config import settings
from .core.database import get_db
from .rate_limit_http import enforce_http, to_http_exception
from .core.rate_limit import RateLimitError
from .services.reactions import ReactionValidationError
from .services.reactions import canonical_participants
from .services.reactions import validate_reaction_draft
from .core.security import Actor, current_actor, public_or_actor, require_scope
from .services.reactions import list_my_reactions

router = APIRouter(tags=["reactions"])
logger = logging.getLogger(__name__)
ROLES = ("REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT")


def chemical_properties(smiles: str) -> dict[str, Any]:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(400, "化合物结构无法通过 RDKit 解析")
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


async def resolve_or_create_chemical(db, smiles: str) -> tuple[int, bool]:
    # 锁键用 canonical 形式: 同一分子的不同写法(CCO/OCC)必须落在同一把锁上,
    # 否则并发双写可各建一行(缝只开一次, 但没必要留). 入参已是 canonical 时零开销.
    # RDKit 解析是 CPU-bound, 下沉线程池防卡事件循环(与 :50 chemical_properties 同口径).
    canonical = await asyncio.to_thread(canonicalize_smiles, smiles) or smiles
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:smiles,0))"), {"smiles": canonical})
    props = await asyncio.to_thread(chemical_properties, canonical)
    inchikey = props.get("inchikey")
    # 0906 治理机制: 定位/裁定改走 identity.resolve_chemical 五状态契约。
    # SMILES 路证据=ik(结构键)。EQUIVALENT(ik 结构行命中)直接用;
    # CONFLICT/AMBIGUOUS 不可能在此形态出现(单键定位), 保守起见仍检查。
    from .services.identity import resolve_chemical
    # create=False: NEW 时不占行 — 完整行(带mol/指纹)由本函数下方 INSERT
    # 一次性建, 避免 resolve 先建裸占位行再建完整行的双行缝(终审0906)
    res = await resolve_chemical(db, inchikey=inchikey, create=False)
    if res.chemical_id is not None and res.status in ("EQUIVALENT", "EXACT"):
        return int(res.chemical_id), False
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
    # 新 INSERT 且 CID=NULL 且合法 IK 非空 → discovery 入列。
    # begin_nested savepoint 隔离 — PostgreSQL SQL error 只回滚 savepoint,
    # 不污染主 reaction transaction(aborted), 主流程可继续 commit。
    if inchikey:
        try:
            # §3 frozen-baseline correction: 局部 import(勿改模块级 ——
            # test_discovery_fix31 monkeypatch api.services.discovery.
            # enqueue_discovery 注入真实 PG error, 局部 import 保持真链)
            from .services.discovery import enqueue_discovery
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




def _reaction_validation_http(exc: ReactionValidationError) -> HTTPException:
    """G3.1B: neutral validation kind → 原 HTTP status(400/409), detail 原文。"""
    if exc.kind == ReactionValidationError.DUPLICATE_PARTICIPANT:
        return HTTPException(409, exc.detail)
    return HTTPException(400, exc.detail)

@router.post(
    "/reactions/validate",
    operation_id="validate_reaction",
    summary="校验并标准化反应草稿",
)
async def validate_reaction(body: ReactionBody, actor: Actor = Depends(current_actor)):
    require_scope(actor, "reaction:write")
    # G3.1B: rate/kernel/assembly 下沉 services.reactions.validate_reaction_draft;
    # adapter 只余 auth/scope + neutral → HTTP 映射(400/409 + G2.R bridge)。
    try:
        return await validate_reaction_draft(actor_id=actor.id, body=body)
    except ReactionValidationError as exc:
        raise _reaction_validation_http(exc) from exc
    except RateLimitError as exc:
        raise to_http_exception(exc) from exc


@router.post(
    "/reactions",
    status_code=201,
    operation_id="create_reaction",
    summary="保存用户确认的反应记录",
)
async def create_reaction(
    body: ReactionBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    require_scope(actor, "reaction:write")
    await enforce_http("reaction-write-minute", str(actor.id), settings.api_reaction_write_limit_per_minute, 60)
    await enforce_http("reaction-write-day", str(actor.id), settings.api_reaction_write_limit_per_day, 86400)
    if actor.auth_kind == "agent" and not idempotency_key:
        raise HTTPException(400, "使用 API Token 提交必须提供 Idempotency-Key")
    if idempotency_key and len(idempotency_key) > 200:
        raise HTTPException(400, "Idempotency-Key 不能超过 200 个字符")
    if idempotency_key:
        existing = (await db.execute(text("""
            SELECT id FROM chemistry.reactions
            WHERE created_by_user_id=:user_id AND idempotency_key=:key
        """), {"user_id": actor.id, "key": idempotency_key})).scalar()
        if existing is not None:
            return await reaction_response(db, int(existing))

    try:
        participants, reaction_smiles = await asyncio.to_thread(canonical_participants, body)
    except ReactionValidationError as exc:
        raise _reaction_validation_http(exc) from exc
    resolved, created_chemicals = await resolve_participants(db, participants)
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
            "user_id": actor.id, "created_via": "agent" if actor.auth_kind == "agent" else "web",
            "idempotency_key": idempotency_key,
        })).scalar_one())
    except IntegrityError:
        await db.rollback()
        if idempotency_key:
            existing = (await db.execute(text("""
                SELECT id FROM chemistry.reactions
                WHERE created_by_user_id=:user_id AND idempotency_key=:key
            """), {"user_id": actor.id, "key": idempotency_key})).scalar()
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
        await notify_new_reaction_safely(db, actor.id, reaction_id)
    return await reaction_response(db, reaction_id, created_chemicals)


@router.put("/reactions/{reaction_id}")
async def update_reaction(
    body: ReactionBody, reaction_id: int = Path(..., ge=1), actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    if actor.auth_kind == "agent":
        raise HTTPException(403, "API Token 当前不开放反应编辑，请使用网页登录会话")
    await enforce_http("reaction-write-minute", str(actor.id), settings.api_reaction_write_limit_per_minute, 60)
    current = (await db.execute(text("""
        SELECT created_by_user_id,visibility,moderation_status
        FROM chemistry.reactions WHERE id=:id FOR UPDATE
    """), {"id": reaction_id})).fetchone()
    if not current:
        raise HTTPException(404, "反应不存在")
    if current[0] != actor.id:
        raise HTTPException(403, "只能维护自己创建的反应")
    try:
        participants, reaction_smiles = await asyncio.to_thread(canonical_participants, body)
    except ReactionValidationError as exc:
        raise _reaction_validation_http(exc) from exc
    resolved, created_chemicals = await resolve_participants(db, participants)
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
    if body.visibility == "public" and current[1] == "private":
        await notify_new_reaction_safely(db, actor.id, reaction_id)
    # D001 修复: 成功更新统一返回既有 response payload(此前 visibility
    # 未变分支 fall-through 返回 None/200 null)。单一成功契约, 复用
    # 既有 reaction_response, 无第二套 assembly。
    return await reaction_response(db, reaction_id, created_chemicals)


@router.delete("/reactions/{reaction_id}", status_code=204)
async def delete_reaction(reaction_id: int = Path(..., ge=1), actor: Actor = Depends(current_actor), db=Depends(get_db)):
    if actor.auth_kind == "agent":
        raise HTTPException(403, "API Token 当前不开放反应删除，请使用网页登录会话")
    record = (await db.execute(text("""
        SELECT created_by_user_id,visibility,moderation_status
        FROM chemistry.reactions WHERE id=:id FOR UPDATE
    """), {"id": reaction_id})).fetchone()
    if record is None:
        raise HTTPException(404, "反应不存在")
    owner = record[0]
    if owner is None:
        raise HTTPException(403, "系统导入反应不能由用户删除")
    if int(owner) != actor.id:
        raise HTTPException(403, "只能删除自己创建的反应")
    await db.execute(text("DELETE FROM chemistry.reactions WHERE id=:id"), {"id": reaction_id})
    if record[1] == "public" and record[2] == "visible":
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=greatest(exact_count-1,0),calculated_at=now()
            WHERE metric='reactions'
        """))
    await db.commit()


@router.get(
    "/users/me/reactions",
    operation_id="list_my_reactions",
    summary="读取当前用户自己的反应记录",
)
async def my_reactions(
    visibility: Literal["all", "public", "private"] = Query("all"),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(20, ge=1, le=50),
    actor: Actor = Depends(current_actor), db=Depends(get_db),
):
    return await list_my_reactions(
        db, actor_id=actor.id, visibility=visibility,
        page=page, page_size=page_size,
    )


@router.get("/users/{username}/reactions")
async def user_reactions(
    username: str, page: int = Query(1, ge=1, le=500), page_size: int = Query(20, ge=1, le=50),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT r.id,r.reaction_smiles,r.visibility,r.created_at,r.updated_at,
          (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=r.id) AS followers
        FROM chemistry.reactions r JOIN community.users u ON u.id=r.created_by_user_id
        WHERE lower(u.username)=lower(:username) AND u.status='active'
          AND r.visibility='public' AND r.moderation_status='visible'
        ORDER BY r.id DESC LIMIT :limit OFFSET :offset
    """), {"username": username, "limit": page_size, "offset": (page-1)*page_size})).mappings().all()
    return [dict(row) for row in rows]
