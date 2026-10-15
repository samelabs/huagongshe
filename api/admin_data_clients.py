"""对外数据服务的凭证管理(仅平台管理员)。

创建、停用/启用、调整额度、列表(含每日用量)。令牌明文只在发放时
返回一次, 库里只存哈希。
"""

from __future__ import annotations

import secrets
from datetime import date

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from .core.database import get_db
from .core.security import Actor, current_session
from .services.data_api.auth import (
    CHEMICAL_READ_SCOPE, REACTION_READ_SCOPE, generate_token, token_hash)

VALID_SCOPES = (CHEMICAL_READ_SCOPE, REACTION_READ_SCOPE)


async def _admin(actor: Actor = Depends(current_session)) -> Actor:
    if actor.role != "admin":
        raise HTTPException(403, "没有平台管理权限")
    return actor


class ClientCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default="", max_length=200)
    scopes: list[str] = Field(min_length=1)
    rate_per_minute: int = Field(default=60, ge=1, le=10_000)
    rate_per_day: int = Field(default=20_000, ge=1, le=1_000_000)
    expires_at: str | None = Field(default=None, max_length=40)


class ClientPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=200)
    scopes: list[str] | None = None
    rate_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    rate_per_day: int | None = Field(default=None, ge=1, le=1_000_000)
    enabled: bool | None = None
    expires_at: str | None = Field(default=None, max_length=40)


async def _validate_scopes(scopes: list[str]) -> list[str]:
    invalid = [s for s in scopes if s not in VALID_SCOPES]
    if invalid:
        raise HTTPException(422, {"message": f"未知 scope: {', '.join(invalid)}",
                                  "kind": "invalid_scope"})
    return sorted(set(scopes))


async def create_client(
    body: ClientCreateBody, actor: Actor = Depends(_admin), db=Depends(get_db),
):
    """发放凭证; 令牌明文只在本次响应返回一次。"""
    scopes = await _validate_scopes(body.scopes)
    client_id = "hgsd-" + secrets.token_hex(8)
    token = generate_token()
    expires = body.expires_at or None
    row = (await db.execute(text("""
        INSERT INTO data_api.clients
            (client_id, name, contact, scopes, rate_per_minute, rate_per_day,
             expires_at, created_by, token_hash)
        VALUES (:cid, :name, :contact, :scopes, :rpm, :rpd,
                CAST(:expires AS timestamptz), :owner, :th)
        RETURNING id, client_id, name, contact, scopes, rate_per_minute,
                  rate_per_day, enabled, expires_at, created_at
    """), {"cid": client_id, "name": body.name.strip(), "contact": body.contact.strip(),
           "scopes": scopes, "rpm": body.rate_per_minute, "rpd": body.rate_per_day,
           "expires": expires, "owner": actor.id, "th": token_hash(token)})).fetchone()
    await db.commit()
    response = JSONResponse({**_client_view(row), "token": token}, status_code=201)
    response.headers["Cache-Control"] = "no-store"
    return response


async def list_clients(actor: Actor = Depends(_admin), db=Depends(get_db)):
    """凭证列表 + 最近用量(今天/昨天)。"""
    rows = (await db.execute(text("""
        SELECT c.id, c.client_id, c.name, c.contact, c.scopes,
               c.rate_per_minute, c.rate_per_day, c.enabled, c.expires_at, c.created_at,
               COALESCE(u.calls, 0), COALESCE(u.errors, 0)
        FROM data_api.clients c
        LEFT JOIN data_api.usage_daily u
               ON u.client_id = c.id AND u.day = :today
        ORDER BY c.id DESC
    """), {"today": date.today()})).fetchall()
    return {"items": [
        {**_client_view(row), "calls_today": int(row[10]), "errors_today": int(row[11])}
        for row in rows]}


async def update_client(
    client_pk: int, body: ClientPatchBody,
    actor: Actor = Depends(_admin), db=Depends(get_db),
):
    """更新名称/联系人/scopes/额度/启用状态/到期时间。"""
    scopes = await _validate_scopes(body.scopes) if body.scopes is not None else None
    sets = []
    params: dict = {"pk": client_pk}
    if body.name is not None:
        sets.append("name = :name"); params["name"] = body.name.strip()
    if body.contact is not None:
        sets.append("contact = :contact"); params["contact"] = body.contact.strip()
    if scopes is not None:
        sets.append("scopes = :scopes"); params["scopes"] = scopes
    if body.rate_per_minute is not None:
        sets.append("rate_per_minute = :rpm"); params["rpm"] = body.rate_per_minute
    if body.rate_per_day is not None:
        sets.append("rate_per_day = :rpd"); params["rpd"] = body.rate_per_day
    if body.enabled is not None:
        sets.append("enabled = :enabled"); params["enabled"] = body.enabled
    if body.expires_at is not None:
        sets.append("expires_at = CAST(:expires AS timestamptz)"); params["expires"] = body.expires_at or None
    if not sets:
        raise HTTPException(422, {"message": "没有可更新的字段", "kind": "empty_update"})
    sets.append("updated_at = now()")
    row = (await db.execute(text(f"""
        UPDATE data_api.clients SET {', '.join(sets)}
        WHERE id = :pk
        RETURNING id, client_id, name, contact, scopes, rate_per_minute,
                  rate_per_day, enabled, expires_at, created_at
    """), params)).fetchone()
    if row is None:
        raise HTTPException(404, {"message": "凭证不存在", "kind": "not_found"})
    await db.commit()
    return _client_view(row)


def _client_view(row) -> dict:
    return {
        "id": row[0], "client_id": row[1], "name": row[2], "contact": row[3],
        "scopes": list(row[4]), "rate_per_minute": row[5], "rate_per_day": row[6],
        "enabled": row[7],
        "expires_at": str(row[8]) if row[8] is not None else None,
        "created_at": str(row[9]),
    }


def register(router) -> None:
    """把凭证管理路由挂到 admin router 上。"""
    router.post("/data-clients", operation_id="admin_create_data_client")(create_client)
    router.get("/data-clients", operation_id="admin_list_data_clients")(list_clients)
    router.patch("/data-clients/{client_pk}", operation_id="admin_update_data_client")(update_client)
