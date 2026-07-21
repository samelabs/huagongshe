"""Authentication shared by the web session and user-owned AI Agent tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException
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
    return {
        "id": actor.id,
        "username": actor.username,
        "display_name": actor.display_name,
        "email": actor.email,
        "role": actor.role,
        "avatar_url": actor.avatar_path,
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
    return await resolve_actor(db, authorization, session_token)


async def current_actor(actor: Actor | None = Depends(optional_actor)) -> Actor:
    if actor is None:
        raise HTTPException(401, "请先登录或提供有效的 Agent Token")
    return actor


def require_scope(actor: Actor, scope: str) -> None:
    if actor.auth_kind == "agent" and scope not in actor.scopes:
        raise HTTPException(403, f"Agent Token 缺少 {scope} 权限")
