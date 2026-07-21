"""Platform governance: accounts and visibility, never scientific approval."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from .cache import cache_delete
from .database import get_db
from .security import Actor, current_actor

router = APIRouter(prefix="/admin", tags=["administration"])


async def admin(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.role != "admin":
        raise HTTPException(403, "没有平台管理权限")
    return actor


class UserStatusBody(BaseModel):
    status: Literal["active", "disabled"]


class ModerationBody(BaseModel):
    status: Literal["visible", "hidden"]


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, max_length=100), limit: int = Query(50, ge=1, le=100),
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT u.id,u.username,u.display_name,u.email,u.role,u.status,u.avatar_path,
               u.created_at,u.last_login_at,
               (SELECT count(*) FROM chemistry.reactions WHERE created_by_user_id=u.id)
        FROM community.users u
        WHERE (:q IS NULL OR u.username ILIKE '%' || :q || '%' OR u.email ILIKE '%' || :q || '%')
        ORDER BY u.id DESC LIMIT :limit
    """), {"q": (q or "").strip() or None, "limit": limit})).mappings().all()
    return [dict(row) for row in rows]


@router.patch("/users/{user_id}/status")
async def set_user_status(
    user_id: int, body: UserStatusBody, actor: Actor = Depends(admin), db=Depends(get_db)
):
    if user_id == actor.id and body.status == "disabled":
        raise HTTPException(409, "不能停用当前管理员账号")
    result = await db.execute(text("""
        UPDATE community.users SET status=:status,updated_at=now() WHERE id=:id
    """), {"id": user_id, "status": body.status})
    if result.rowcount == 0:
        raise HTTPException(404, "用户不存在")
    if body.status == "disabled":
        await db.execute(text("DELETE FROM community.sessions WHERE user_id=:id"), {"id": user_id})
        await db.execute(text("""
            UPDATE community.user_api_tokens SET revoked_at=coalesce(revoked_at,now()) WHERE user_id=:id
        """), {"id": user_id})
    await db.commit()
    return {"id": user_id, "status": body.status}


@router.get("/reactions")
async def list_user_reactions(
    status: Literal["all", "visible", "hidden"] = Query("all"),
    limit: int = Query(50, ge=1, le=100), actor: Actor = Depends(admin), db=Depends(get_db),
):
    clause = "" if status == "all" else "AND r.moderation_status=:status"
    rows = (await db.execute(text(f"""
        SELECT r.id,r.reaction_smiles,r.visibility,r.moderation_status,r.created_at,r.updated_at,
               u.username,u.display_name
        FROM chemistry.reactions r JOIN community.users u ON u.id=r.created_by_user_id
        WHERE true {clause} ORDER BY r.id DESC LIMIT :limit
    """), {"status": status, "limit": limit})).mappings().all()
    return [dict(row) for row in rows]


@router.patch("/reactions/{reaction_id}/moderation")
async def moderate_reaction(
    reaction_id: int, body: ModerationBody, actor: Actor = Depends(admin), db=Depends(get_db)
):
    current = (await db.execute(text("""
        SELECT moderation_status,visibility FROM chemistry.reactions
        WHERE id=:id AND created_by_user_id IS NOT NULL FOR UPDATE
    """), {"id": reaction_id})).fetchone()
    if not current:
        raise HTTPException(404, "用户反应不存在")
    await db.execute(text("""
        UPDATE chemistry.reactions SET moderation_status=:status,updated_at=now() WHERE id=:id
    """), {"id": reaction_id, "status": body.status})
    if current[1] == "public" and current[0] != body.status:
        delta = -1 if body.status == "hidden" else 1
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=greatest(exact_count+:delta,0),calculated_at=now()
            WHERE metric='reactions'
        """), {"delta": delta})
    if body.status == "hidden":
        await db.execute(text("DELETE FROM community.reaction_follows WHERE reaction_id=:id"), {"id": reaction_id})
    await db.commit()
    if current[1] == "public" and current[0] != body.status:
        await cache_delete("v1:stats:exact")
    return {"id": reaction_id, "moderation_status": body.status}
