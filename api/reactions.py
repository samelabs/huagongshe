"""The single write path for web users and their AI Agents."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from sqlalchemy import text

from .schemas.reactions import ReactionBody
from .core.database import get_db
from .rate_limit_http import to_http_exception
from .core.rate_limit import RateLimitError
from .services.reactions import (AgentReactionMutationForbiddenError,
                                 ReactionAccessError, ReactionValidationError)
from .services.reactions import validate_reaction_draft
from .core.security import Actor, current_actor, public_or_actor, require_scope
from .services.reactions import list_my_reactions
from .services.reactions import (IdempotencyKeyTooLongError,
                                 MissingIdempotencyKeyError)
from .services.reactions import (
    UnresolvedIdentityError as _UnresolvedIdentityError,
    create_reaction as create_reaction_service,
)
from .services.reactions import delete_reaction as delete_reaction_service
from .services.reactions import update_reaction as update_reaction_service

router = APIRouter(tags=["reactions"])
logger = logging.getLogger(__name__)
ROLES = ("REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT")


def _reaction_validation_http(exc: ReactionValidationError) -> HTTPException:
    """G3.1B: neutral validation kind → 原 HTTP status(400/409), detail 原文。"""
    if exc.kind == ReactionValidationError.DUPLICATE_PARTICIPANT:
        return HTTPException(409, exc.detail)
    return HTTPException(400, exc.detail)


def _reaction_access_http(exc: ReactionAccessError) -> HTTPException:
    """E3: neutral 存在性/所有权 kind → 原 HTTP status(404/403), detail 原文。"""
    if exc.kind == ReactionAccessError.NOT_FOUND:
        return HTTPException(404, exc.detail)
    return HTTPException(403, exc.detail)

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
    except _UnresolvedIdentityError as exc:
        raise HTTPException(409, exc.detail) from exc


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
    except _UnresolvedIdentityError as exc:
        # E9-B: CONFLICT/AMBIGUOUS → 409, 未创建任何行
        raise HTTPException(409, exc.detail) from exc


@router.put("/reactions/{reaction_id}")
async def update_reaction(
    body: ReactionBody, reaction_id: int = Path(..., ge=1), actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    # E3: 行锁/owner 规则/参与者替换/关系替换/可见性与统计/事务/通知全部
    # 下沉 services.reactions.update_reaction(唯一业务 owner); adapter 只余
    # auth + neutral 错误 → HTTP 映射(403/404/400/409/429)。
    try:
        return await update_reaction_service(
            db, actor_id=actor.id, auth_kind=actor.auth_kind,
            reaction_id=reaction_id, body=body)
    except AgentReactionMutationForbiddenError as exc:
        raise HTTPException(403, exc.detail) from exc
    except ReactionAccessError as exc:
        raise _reaction_access_http(exc) from exc
    except ReactionValidationError as exc:
        raise _reaction_validation_http(exc) from exc
    except RateLimitError as exc:
        raise to_http_exception(exc) from exc
    except _UnresolvedIdentityError as exc:
        # E9-B: CONFLICT/AMBIGUOUS → 409, 参与者/反应行零写入
        raise HTTPException(409, exc.detail) from exc


@router.delete("/reactions/{reaction_id}", status_code=204)
async def delete_reaction(reaction_id: int = Path(..., ge=1), actor: Actor = Depends(current_actor), db=Depends(get_db)):
    # E3: 行锁/系统导入与 owner 规则/删除/统计/事务下沉
    # services.reactions.delete_reaction(唯一业务 owner)。
    try:
        await delete_reaction_service(
            db, actor_id=actor.id, auth_kind=actor.auth_kind,
            reaction_id=reaction_id)
    except AgentReactionMutationForbiddenError as exc:
        raise HTTPException(403, exc.detail) from exc
    except ReactionAccessError as exc:
        raise _reaction_access_http(exc) from exc


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
