"""The single write path for web users and their AI Agents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from sqlalchemy import text

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
from .services.reactions import (IdempotencyKeyTooLongError,
                                 MissingIdempotencyKeyError)
from .services.reactions import create_reaction as create_reaction_service
from .services.reactions import (notify_new_reaction_safely,
                                 reaction_response, reaction_values,
                                 resolve_or_create_chemical,
                                 resolve_participants,
                                 write_relationships)

router = APIRouter(tags=["reactions"])
logger = logging.getLogger(__name__)
ROLES = ("REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT")


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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    # G3.1C: request 参数已删(体内零消费, AST 核实); rate/幂等/校验/事务/
    # 响应全部下沉 services.reactions.create_reaction; adapter 只余
    # auth/scope + neutral → HTTP 映射。§8 顺序: rate 先于 key 校验(service 内)。
    require_scope(actor, "reaction:write")
    try:
        return await create_reaction_service(
            db, actor_id=actor.id, auth_kind=actor.auth_kind,
            body=body, idempotency_key=idempotency_key)
    except ReactionValidationError as exc:
        raise _reaction_validation_http(exc) from exc
    except MissingIdempotencyKeyError as exc:
        raise HTTPException(400, exc.detail) from exc
    except IdempotencyKeyTooLongError as exc:
        raise HTTPException(400, exc.detail) from exc
    except RateLimitError as exc:
        raise to_http_exception(exc) from exc


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
