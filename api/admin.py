"""Platform governance: accounts, visibility, configuration and dashboard."""

from __future__ import annotations

import json
import shutil
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from .cache import cache_delete, cache_get, cache_set
from .database import get_db
from .security import Actor, current_session

router = APIRouter(prefix="/admin", tags=["administration"], include_in_schema=False)


async def admin(actor: Actor = Depends(current_session)) -> Actor:
    if actor.role != "admin":
        raise HTTPException(403, "没有平台管理权限")
    return actor


class UserStatusBody(BaseModel):
    status: Literal["active", "disabled"]


class UserRoleBody(BaseModel):
    role: Literal["member", "admin"]


class ModerationBody(BaseModel):
    status: Literal["visible", "hidden"]


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, max_length=100), limit: int = Query(50, ge=1, le=100),
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    search = (q or "").strip()
    if search:
        rows = (await db.execute(text("""
            SELECT u.id,u.username,u.display_name,u.email,u.role,u.status,u.avatar_path,
                   u.created_at,u.last_login_at,
                   (SELECT count(*) FROM chemistry.reactions WHERE created_by_user_id=u.id)
            FROM community.users u
            WHERE u.username ILIKE '%' || :q || '%' OR u.email ILIKE '%' || :q || '%'
            ORDER BY u.id DESC LIMIT :limit
        """), {"q": search, "limit": limit})).mappings().all()
    else:
        rows = (await db.execute(text("""
            SELECT u.id,u.username,u.display_name,u.email,u.role,u.status,u.avatar_path,
                   u.created_at,u.last_login_at,
                   (SELECT count(*) FROM chemistry.reactions WHERE created_by_user_id=u.id)
            FROM community.users u
            ORDER BY u.id DESC LIMIT :limit
        """), {"limit": limit})).mappings().all()
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


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: int, body: UserRoleBody, actor: Actor = Depends(admin), db=Depends(get_db)
):
    if user_id == actor.id and body.role != "admin":
        raise HTTPException(409, "不能移除自己的管理员权限")
    result = await db.execute(text("""
        UPDATE community.users SET role=:role, updated_at=now() WHERE id=:id
    """), {"id": user_id, "role": body.role})
    if result.rowcount == 0:
        raise HTTPException(404, "用户不存在")
    await db.commit()
    return {"id": user_id, "role": body.role}


@router.get("/reactions")
async def list_user_reactions(
    status: Literal["all", "visible", "hidden"] = Query("all"),
    limit: int = Query(50, ge=1, le=100), actor: Actor = Depends(admin), db=Depends(get_db),
):
    if status == "all":
        rows = (await db.execute(text("""
            SELECT r.id,r.reaction_smiles,r.visibility,r.moderation_status,r.created_at,r.updated_at,
                   u.username,u.display_name
            FROM chemistry.reactions r JOIN community.users u ON u.id=r.created_by_user_id
            WHERE r.created_by_user_id IS NOT NULL
            ORDER BY r.id DESC LIMIT :limit
        """), {"limit": limit})).mappings().all()
    else:
        rows = (await db.execute(text("""
            SELECT r.id,r.reaction_smiles,r.visibility,r.moderation_status,r.created_at,r.updated_at,
                   u.username,u.display_name
            FROM chemistry.reactions r JOIN community.users u ON u.id=r.created_by_user_id
            WHERE r.created_by_user_id IS NOT NULL AND r.moderation_status=:status
            ORDER BY r.id DESC LIMIT :limit
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


# ── 仪表盘 ──────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(actor: Actor = Depends(admin), db=Depends(get_db)):
    """全局运行状态概览。"""
    row = (await db.execute(text("""
        SELECT
          (SELECT count(*) FROM community.users),
          (SELECT count(*) FROM community.users WHERE created_at >= current_date),
          (SELECT count(*) FROM community.users WHERE created_at >= current_date - interval '7 days'),
          (SELECT count(*) FROM community.sessions),
          (SELECT count(*) FROM community.user_api_tokens),
          (SELECT count(*) FROM community.user_api_tokens WHERE revoked_at IS NULL),
          (SELECT exact_count FROM chemistry.statistics WHERE metric='reactions'),
          (SELECT count(*) FROM chemistry.reactions WHERE created_by_user_id IS NOT NULL),
          (SELECT count(*) FROM chemistry.reactions WHERE created_by_user_id IS NOT NULL AND created_at >= current_date),
          (SELECT exact_count FROM chemistry.statistics WHERE metric='chemicals')
    """))).fetchone()
    disk = shutil.disk_usage("/")
    return {
        "users": {"total": row[0], "today": row[1], "week": row[2]},
        "sessions": row[3],
        "tokens": {"total": row[4], "active": row[5]},
        "reactions": {
            "total": row[6] or 0,
            "user_created": row[7],
            "today": row[8],
        },
        "chemicals": row[9] or 0,
        "system": {
            "disk_total_gb": round(disk.total / 1e9, 1),
            "disk_used_gb": round(disk.used / 1e9, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
            "disk_pct": round(disk.used / disk.total * 100, 1),
        },
    }


# ── 系统配置 ────────────────────────────────────────────

# 允许通过 API 写入的 namespace/key 白名单
CONFIG_SCHEMA: dict[str, set[str]] = {
    "analytics": {"scripts"},
    "ads": {"adsense"},
    "site": {"meta"},
    "branding": {"slogan"},
}


@router.get("/config")
async def list_config(actor: Actor = Depends(admin), db=Depends(get_db)):
    """读取全部系统配置。"""
    rows = (await db.execute(text("""
        SELECT namespace, key, value FROM community.system_config ORDER BY namespace, key
    """))).fetchall()
    return [
        {"namespace": r[0], "key": r[1], "value": json.loads(r[2]) if isinstance(r[2], str) else r[2]}
        for r in rows
    ]


@router.put("/config/{namespace}/{key}")
async def update_config(
    namespace: str, key: str, body: dict[str, Any],
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    """写入单条配置。"""
    if namespace not in CONFIG_SCHEMA or key not in CONFIG_SCHEMA[namespace]:
        raise HTTPException(400, f"不支持的配置项: {namespace}/{key}")
    result = await db.execute(text("""
        INSERT INTO community.system_config (namespace, key, value, updated_at)
        VALUES (:ns, :key, CAST(:value AS jsonb), now())
        ON CONFLICT (namespace, key) DO UPDATE SET value = CAST(:value AS jsonb), updated_at = now()
    """), {"ns": namespace, "key": key, "value": json.dumps(body)})
    await db.commit()
    await cache_delete("config:public:all")
    return {"namespace": namespace, "key": key, "value": body}

