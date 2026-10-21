"""HTTP adapter for user Notes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text

from .core.database import get_db
from .core.rate_limit import RateLimitError
from .core.security import Actor, current_session, public_or_actor
from .rate_limit_http import to_http_exception
from .schemas.notes import NoteBody
from .services.notes import (
    NoteEntityNotFoundError,
    NoteNotAccessibleError,
    NoteQuotaExceededError,
    NoteReferenceError,
    create_note as create_note_service,
    delete_note as delete_note_service,
    get_note as get_note_service,
    list_entity_notes,
    list_my_notes,
    list_public_user_notes,
    update_note as update_note_service,
)

router = APIRouter(tags=["notes"])


def _note_not_found(exc: Exception) -> HTTPException:
    return HTTPException(404, {"message": str(exc), "kind": "note_not_found"})


# FX 回执遗留: 超大 ID(>int32)此前穿进 SQL 撞 asyncpg DataError → 500;
# 与 skills 端点同口径收 le=2^31-1 → 422(前端 isApiGone 同道 404 呈现)。


@router.post("/notes", status_code=201)
async def create_note(
    body: NoteBody,
    actor: Actor = Depends(current_session),
    db=Depends(get_db),
):
    try:
        return await create_note_service(
            db,
            actor_id=actor.id,
            visibility=body.visibility,
            content=body.content,
            title=body.title,
            chemical_ids=body.chemical_ids,
            reaction_ids=body.reaction_ids,
        )
    except RateLimitError as exc:
        # 服务层 neutral 限流异常在 HTTP 边界统一映射
        # (RateLimited→429, LimiterUnavailable→503), 与 reactions 等同口径。
        raise to_http_exception(exc) from exc
    except NoteReferenceError as exc:
        # detail 为 {message, kind} 结构 — message 保持中文
        # 原文, kind 是稳定机器码(前端五语言分类); 纯字符串消费者的旧
        # 形态由 ApiError 结构分支兼容。
        raise HTTPException(
            400, {"message": str(exc), "kind": exc.kind}) from exc
    except NoteQuotaExceededError as exc:
        # 笔记每用户存量上限 — 409 + 机器码, 前端按 kind 本地化
        raise HTTPException(
            409, {"message": str(exc), "kind": exc.kind}) from exc


@router.get("/notes/{ref}")
async def get_note(
    ref: str = Path(..., min_length=1, max_length=64, pattern=r"^[a-z0-9]+$"),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    try:
        # 公开笔记匿名可读; 私有仅属主会话(Web)。ref = 数字 id 或 7 位 slug,
        # 旧 id 链接不失效。机器会话不读私有(Notes 无 Agent 契约前不扩面)。
        owner_session_id = (
            actor.id if actor is not None and actor.auth_kind == "session" else None
        )
        return await get_note_service(
            db, note_ref=ref, actor_id=owner_session_id)
    except NoteNotAccessibleError as exc:
        raise _note_not_found(exc) from exc


@router.put("/notes/{note_id}")
async def update_note(
    body: NoteBody,
    note_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor = Depends(current_session),
    db=Depends(get_db),
):
    try:
        return await update_note_service(
            db,
            note_id=note_id,
            actor_id=actor.id,
            visibility=body.visibility,
            content=body.content,
            title=body.title,
            chemical_ids=body.chemical_ids,
            reaction_ids=body.reaction_ids,
        )
    except RateLimitError as exc:
        # 同 create_note — 编辑限流同桶, HTTP 映射同口径。
        raise to_http_exception(exc) from exc
    except NoteNotAccessibleError as exc:
        raise _note_not_found(exc) from exc
    except NoteReferenceError as exc:
        # detail 为 {message, kind} 结构 — message 保持中文
        # 原文, kind 是稳定机器码(前端五语言分类); 纯字符串消费者的旧
        # 形态由 ApiError 结构分支兼容。
        raise HTTPException(
            400, {"message": str(exc), "kind": exc.kind}) from exc


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: int = Path(..., ge=1, le=2_147_483_647),
    actor: Actor = Depends(current_session),
    db=Depends(get_db),
):
    try:
        await delete_note_service(db, note_id=note_id, actor_id=actor.id)
    except NoteNotAccessibleError as exc:
        raise _note_not_found(exc) from exc


@router.get("/users/me/notes")
async def my_notes(
    visibility: Literal["all", "public", "private"] = Query("all"),
    chemical_id: int | None = Query(default=None, ge=1),
    reaction_id: int | None = Query(default=None, ge=1),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    actor: Actor = Depends(current_session),
    db=Depends(get_db),
):
    return await list_my_notes(
        db,
        actor_id=actor.id,
        visibility=visibility,
        chemical_id=chemical_id,
        reaction_id=reaction_id,
        page=page,
        page_size=page_size,
    )


@router.get("/users/{username}/notes")
async def public_user_notes(
    username: str,
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    """Public notes of an active user, for the public profile page.

    Registered after /users/me/notes so the literal path wins for `me`.
    Inactive or missing users 404; private/hidden notes never appear.
    """
    if username == "me":  # pragma: no cover - guarded by route order
        raise HTTPException(404, {"message": "用户不存在", "kind": "user_not_found"})
    user_row = (await db.execute(text("""
        SELECT id FROM community.users
        WHERE lower(username)=lower(:username) AND status='active'
    """), {"username": username})).scalar()
    if user_row is None:
        raise HTTPException(404, {"message": "用户不存在", "kind": "user_not_found"})
    return await list_public_user_notes(
        db, user_id=int(user_row), page=page, page_size=page_size,
    )


@router.get("/chemicals/{chemical_id}/notes")
async def chemical_notes(
    chemical_id: int = Path(..., ge=1, le=2_147_483_647),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    try:
        return await list_entity_notes(
            db,
            entity="chemical",
            entity_id=chemical_id,
            page=page,
            page_size=page_size,
        )
    except NoteEntityNotFoundError as exc:
        raise _note_not_found(exc) from exc


@router.get("/reactions/{reaction_id}/notes")
async def reaction_notes(
    reaction_id: int = Path(..., ge=1, le=2_147_483_647),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    try:
        return await list_entity_notes(
            db,
            entity="reaction",
            entity_id=reaction_id,
            page=page,
            page_size=page_size,
        )
    except NoteEntityNotFoundError as exc:
        raise _note_not_found(exc) from exc
