"""Authentication shared by the web session and user-owned API tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import text

from .config import settings
from .database import get_db


@dataclass(frozen=True)
class Actor:
    id: int
    username: str
    display_name: str
    email: str
    role: str
    avatar_path: str | None
    auth_kind: str
    token_id: int | None = None
    scopes: tuple[str, ...] = ()


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def actor_payload(actor: Actor) -> dict:
    # 会话/API Key 只在在用账号上成立(停用即全部撤销) —— active 恒为真,
    # 与其余用户投影的四字段口径一致。
    return {
        "id": actor.id,
        "username": actor.username,
        "display_name": actor.display_name,
        "email": actor.email,
        "role": actor.role,
        "avatar_url": actor.avatar_path,
        "active": True,
        "auth_kind": actor.auth_kind,
    }


async def resolve_actor(db, authorization: str | None, session_token: str | None) -> Actor | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if len(token) < 32:
            return None
        digest = hashlib.sha256(token.encode()).digest()
        row = (await db.execute(text("""
            SELECT u.id,u.username,u.display_name,u.email,u.role,u.avatar_path,
                   t.id,t.scopes
            FROM community.user_api_tokens t
            JOIN community.users u ON u.id=t.user_id
            WHERE t.token_hash=:digest AND t.revoked_at IS NULL
              AND (t.expires_at IS NULL OR t.expires_at>now()) AND u.status='active'
        """), {"digest": digest})).fetchone()
        if not row:
            return None
        await db.execute(text("""
            UPDATE community.user_api_tokens SET last_used_at=now()
            WHERE id=:id AND (last_used_at IS NULL OR last_used_at<now()-interval '5 minutes')
        """), {"id": row[6]})
        await db.commit()
        return Actor(
            int(row[0]), row[1], row[2], row[3], row[4], row[5], "agent",
            int(row[6]), tuple(row[7] or ()),
        )
    if session_token:
        digest = hashlib.sha256(session_token.encode()).digest()
        row = (await db.execute(text("""
            SELECT u.id,u.username,u.display_name,u.email,u.role,u.avatar_path
            FROM community.sessions s
            JOIN community.users u ON u.id=s.user_id
            WHERE s.token_hash=:digest AND s.expires_at>now() AND u.status='active'
        """), {"digest": digest})).fetchone()
        if row:
            return Actor(int(row[0]), row[1], row[2], row[3], row[4], row[5], "session")
    return None


async def optional_actor(
    authorization: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie),
    db=Depends(get_db),
) -> Actor | None:
    actor = await resolve_actor(db, authorization, session_token)
    # REST 只供网站内部使用, AI Key(agent)只能用于 MCP。
    # 在 HTTP 依赖层统一拒绝(本函数是 current_actor/public_or_actor 的共同
    # 上游, 覆盖全部 REST 路由); MCP 的 _actor_from_headers 直调
    # resolve_actor, 不经过这里, AI Key 接入 MCP 不受影响。
    # 选 401 而非 403: AI Key 对 REST 是"不被接受的凭据类型"(认证层语义,
    # 同未登录桶), 前端可复用既有 401 处理, 不与"凭据有效但缺权限"混淆。
    if actor is not None and actor.auth_kind == "agent":
        raise HTTPException(401, {
            "message": "API Token 仅支持 MCP 接入，网页接口请使用登录会话",
            "kind": "rest_agent_forbidden",
        })
    return actor


async def current_actor(actor: Actor | None = Depends(optional_actor)) -> Actor:
    if actor is None:
        raise HTTPException(401, {"message": "请先登录", "kind": "login_required"})
    return actor


async def public_or_actor(
    actor: Actor | None = Depends(optional_actor),
) -> Actor | None:
    """公开数据读 dependency(H1 方案 D): 匿名与已鉴权 actor 都可读。

    loopback 不再是 authorization evidence —— 本 dependency 不读取
    Request / client.host / XFF, transport 不是权限; 公开数据是否可读
    由产品 use-case policy 决定, 与来源无关。端点自身可再叠加业务墙
    (如结构检索 mode!=exact 需已鉴权 actor)。
    """
    return actor


async def current_session(actor: Actor = Depends(current_actor)) -> Actor:
    """Require an interactive web session for account and community mutations."""
    if actor.auth_kind != "session":
        raise HTTPException(403, {"message": "该操作必须使用网页登录会话", "kind": "session_required"})
    return actor
