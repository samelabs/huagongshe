"""HTTP adapter for user Notes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text

from .core.database import get_db
from .core.security import Actor, current_session, public_or_actor
from .schemas.notes import NoteBody
from .services.notes import (
    NoteEntityNotFoundError,
    NoteNotAccessibleError,
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
    return HTTPException(404, str(exc))


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
            chemical_ids=body.chemical_ids,
            reaction_ids=body.reaction_ids,
        )
    except NoteReferenceError as exc:
        # v1.7.0 L2: detail 升级为 {message, kind} 结构 — message 保持中文
        # 原文, kind 是稳定机器码(前端五语言分类); 纯字符串消费者的旧
        # 形态由 ApiError 结构分支兼容。
        raise HTTPException(
            400, {"message": str(exc), "kind": exc.kind}) from exc


@router.get("/notes/{note_id}")
async def get_note(
    note_id: int = Path(..., ge=1),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    try:
        # Public notes are anonymous-readable. Private owner context is Web-only
        # in v1.7.0: an API Key/other machine actor must not silently gain a
        # private Notes read surface before Notes has an explicit Agent contract.
        owner_session_id = (
            actor.id if actor is not None and actor.auth_kind == "session" else None
        )
        return await get_note_service(
            db, note_id=note_id, actor_id=owner_session_id)
    except NoteNotAccessibleError as exc:
        raise _note_not_found(exc) from exc


@router.put("/notes/{note_id}")
async def update_note(
    body: NoteBody,
    note_id: int = Path(..., ge=1),
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
            chemical_ids=body.chemical_ids,
            reaction_ids=body.reaction_ids,
        )
    except NoteNotAccessibleError as exc:
        raise _note_not_found(exc) from exc
    except NoteReferenceError as exc:
        # v1.7.0 L2: detail 升级为 {message, kind} 结构 — message 保持中文
        # 原文, kind 是稳定机器码(前端五语言分类); 纯字符串消费者的旧
        # 形态由 ApiError 结构分支兼容。
        raise HTTPException(
            400, {"message": str(exc), "kind": exc.kind}) from exc


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: int = Path(..., ge=1),
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
        raise HTTPException(404, "用户不存在")
    user_row = (await db.execute(text("""
        SELECT id FROM community.users
        WHERE lower(username)=lower(:username) AND status='active'
    """), {"username": username})).scalar()
    if user_row is None:
        raise HTTPException(404, "用户不存在")
    return await list_public_user_notes(
        db, user_id=int(user_row), page=page, page_size=page_size,
    )


@router.get("/chemicals/{chemical_id}/notes")
async def chemical_notes(
    chemical_id: int = Path(..., ge=1),
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
    reaction_id: int = Path(..., ge=1),
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
