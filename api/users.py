"""Accounts, public profiles, avatars and user-owned API tokens."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, Request, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .agent import agent_connection_text
from .config import settings
from .database import get_db
from .rate_limit import enforce, request_identity
from .security import (
    Actor, actor_payload, current_actor, current_session, optional_actor,
    password_hash, password_matches,
)

auth_router = APIRouter(prefix="/auth", tags=["users"])
router = APIRouter(prefix="/users", tags=["users"])
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,30}$")


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("用户名仅支持 2–30 位中文、字母、数字、_ 或 -")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("密码至少包含一个字母和一个数字")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self


class LoginBody(BaseModel):
    account: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ProfileBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("bio")
    @classmethod
    def clean_bio(cls, value: str | None) -> str | None:
        result = (value or "").strip()
        return result or None


class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)

    @model_validator(mode="after")
    def valid_password(self):
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if not re.search(r"[A-Za-z]", self.new_password) or not re.search(r"\d", self.new_password):
            raise ValueError("新密码至少包含一个字母和一个数字")
        return self


def avatar_variants(raw: bytes) -> dict[int, bytes]:
    """Decode, resize and compress outside the API event loop."""
    try:
        source = Image.open(io.BytesIO(raw))
        if source.width * source.height > 20_000_000:
            raise HTTPException(413, "头像像素尺寸过大")
        source.seek(0)
        source = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "无法识别头像图片") from exc
    result: dict[int, bytes] = {}
    for size in (512, 128):
        rendered = ImageOps.fit(source, (size, size), method=Image.Resampling.LANCZOS)
        output = io.BytesIO()
        rendered.save(output, "WEBP", quality=82, method=6)
        result[size] = output.getvalue()
    return result


async def create_session(db, response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_days)
    await db.execute(text("""
        INSERT INTO community.sessions(user_id,token_hash,expires_at)
        VALUES (:user_id,:digest,:expires)
    """), {"user_id": user_id, "digest": hashlib.sha256(token.encode()).digest(), "expires": expires})
    await db.commit()
    response.set_cookie(
        settings.session_cookie, token, max_age=settings.session_days * 86400,
        httponly=True, secure=True, samesite="lax", path="/",
    )


@auth_router.post("/register", status_code=201)
async def register(body: RegisterBody, request: Request, response: Response, db=Depends(get_db)):
    await enforce("register", request_identity(request), 5, 3600)
    encoded_password = await asyncio.to_thread(password_hash, body.password)
    try:
        row = (await db.execute(text("""
            INSERT INTO community.users(username,display_name,email,password_hash)
            VALUES (:username,:username,:email,:password_hash)
            RETURNING id,username,display_name,email,role,avatar_path
        """), {
            "username": body.username, "email": body.email,
            "password_hash": encoded_password,
        })).one()
        await create_session(db, response, int(row[0]))
        return {
            "id": row[0], "username": row[1], "display_name": row[2], "email": row[3],
            "role": row[4], "avatar_url": row[5], "auth_kind": "session",
        }
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "用户名或邮箱已被使用") from exc


@auth_router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, db=Depends(get_db)):
    await enforce("login", request_identity(request), 15, 900)
    account = body.account.strip().lower()
    row = (await db.execute(text("""
        SELECT id,username,display_name,email,role,password_hash,avatar_path
        FROM community.users
        WHERE (lower(email)=:account OR lower(username)=:account) AND status='active'
    """), {"account": account})).fetchone()
    if not row or not await asyncio.to_thread(password_matches, body.password, row[5]):
        raise HTTPException(401, "账号或密码不正确")
    await db.execute(text("UPDATE community.users SET last_login_at=now() WHERE id=:id"), {"id": row[0]})
    await create_session(db, response, int(row[0]))
    return {
        "id": row[0], "username": row[1], "display_name": row[2], "email": row[3],
        "role": row[4], "avatar_url": row[6], "auth_kind": "session",
    }


@auth_router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie),
    db=Depends(get_db),
):
    if session_token:
        await db.execute(text("DELETE FROM community.sessions WHERE token_hash=:digest"), {
            "digest": hashlib.sha256(session_token.encode()).digest()
        })
        await db.commit()
    response.delete_cookie(settings.session_cookie, path="/")


@router.get("/me")
async def me(actor: Actor = Depends(current_actor)):
    result = actor_payload(actor)
    if actor.auth_kind == "agent":
        result.pop("email", None)
    return result


@router.get("/me/dashboard")
async def dashboard_summary(actor: Actor = Depends(current_actor), db=Depends(get_db)):
    row = (await db.execute(text("""
        SELECT u.username,u.display_name,u.bio,u.avatar_path,u.created_at,
          (SELECT count(*) FROM chemistry.reactions r
           WHERE r.created_by_user_id=u.id AND r.visibility='public' AND r.moderation_status='visible'),
          (SELECT count(*) FROM chemistry.reactions r
           WHERE r.created_by_user_id=u.id AND r.visibility='private'),
          (SELECT count(*) FROM community.user_follows f WHERE f.follower_user_id=u.id),
          (SELECT count(*) FROM community.user_follows f WHERE f.followed_user_id=u.id),
          (SELECT count(*) FROM community.chemical_follows f WHERE f.user_id=u.id),
          (SELECT count(*) FROM community.reaction_follows f
           JOIN chemistry.reactions r ON r.id=f.reaction_id
           WHERE f.user_id=u.id AND r.visibility='public' AND r.moderation_status='visible'),
          (SELECT count(*)
           FROM community.notifications n
           JOIN chemistry.reactions r ON r.id=n.reaction_id
           JOIN community.users source_user
             ON source_user.id=n.actor_user_id AND source_user.status='active'
           JOIN community.user_follows current_follow
             ON current_follow.follower_user_id=n.user_id
            AND current_follow.followed_user_id=n.actor_user_id
            AND n.created_at>=current_follow.created_at
           WHERE n.user_id=u.id AND n.event_type='new_reaction' AND n.read_at IS NULL
             AND r.visibility='public' AND r.moderation_status='visible')
        FROM community.users u WHERE u.id=:id AND u.status='active'
    """), {"id": actor.id})).one()
    return {
        "username": row[0], "display_name": row[1], "bio": row[2], "avatar_url": row[3],
        "created_at": row[4],
        "counts": {
            "public_reactions": row[5], "private_reactions": row[6],
            "following": row[7], "followers": row[8],
            "chemicals": row[9], "reactions": row[10], "unread": row[11],
        },
    }


@router.patch("/me")
async def update_profile(body: ProfileBody, actor: Actor = Depends(current_session), db=Depends(get_db)):
    await db.execute(text("""
        UPDATE community.users SET display_name=:display_name,bio=:bio,updated_at=now()
        WHERE id=:id
    """), {"id": actor.id, **body.model_dump()})
    await db.commit()
    return {"display_name": body.display_name, "bio": body.bio}


@router.post("/me/password", status_code=204)
async def change_password(
    body: PasswordBody, response: Response, actor: Actor = Depends(current_session), db=Depends(get_db)
):
    encoded = (await db.execute(text(
        "SELECT password_hash FROM community.users WHERE id=:id"
    ), {"id": actor.id})).scalar_one()
    if not await asyncio.to_thread(password_matches, body.current_password, encoded):
        raise HTTPException(400, "当前密码不正确")
    new_password_hash = await asyncio.to_thread(password_hash, body.new_password)
    await db.execute(text("""
        UPDATE community.users SET password_hash=:password_hash,updated_at=now() WHERE id=:id
    """), {"id": actor.id, "password_hash": new_password_hash})
    await db.execute(text("DELETE FROM community.sessions WHERE user_id=:id"), {"id": actor.id})
    await db.execute(text("""
        UPDATE community.user_api_tokens SET revoked_at=coalesce(revoked_at,now()) WHERE user_id=:id
    """), {"id": actor.id})
    await db.commit()
    response.delete_cookie(settings.session_cookie, path="/")


@router.post("/me/avatar")
async def upload_avatar(
    image: UploadFile = File(...), actor: Actor = Depends(current_session), db=Depends(get_db)
):
    await enforce("avatar", str(actor.id), settings.api_avatar_limit_per_hour, 3600)
    raw = await image.read(settings.avatar_max_bytes + 1)
    if len(raw) > settings.avatar_max_bytes:
        raise HTTPException(413, "头像文件不能超过 5 MB")
    variants = await asyncio.to_thread(avatar_variants, raw)

    version = secrets.token_hex(10)
    user_dir = os.path.join(settings.avatar_root, str(actor.id))
    os.makedirs(user_dir, mode=0o755, exist_ok=True)
    final_names = {512: f"{version}.webp", 128: f"{version}-128.webp"}
    temporary: list[tuple[str, str]] = []
    try:
        old_path = (await db.execute(text(
            "SELECT avatar_path FROM community.users WHERE id=:id"
        ), {"id": actor.id})).scalar()
        for size, filename in final_names.items():
            with tempfile.NamedTemporaryFile(dir=user_dir, suffix=".webp", delete=False) as handle:
                handle.write(variants[size])
                temporary.append((handle.name, os.path.join(user_dir, filename)))
        for temporary_path, final_path in temporary:
            os.replace(temporary_path, final_path)
            os.chmod(final_path, 0o644)
        public_path = f"/uploads/avatars/{actor.id}/{final_names[512]}"
        await db.execute(text("""
            UPDATE community.users
            SET avatar_path=:path,avatar_version=:version,updated_at=now()
            WHERE id=:id
        """), {"path": public_path, "version": version, "id": actor.id})
        await db.commit()
    except Exception:
        for temporary_path, final_path in temporary:
            for path in (temporary_path, final_path):
                if os.path.exists(path):
                    os.unlink(path)
        raise
    if old_path and old_path != public_path and old_path.startswith("/uploads/avatars/"):
        old_name = os.path.basename(old_path)
        for name in (old_name, old_name.replace(".webp", "-128.webp")):
            candidate = os.path.join(user_dir, name)
            if os.path.exists(candidate):
                os.unlink(candidate)
    return {"avatar_url": public_path, "thumbnail_url": public_path.replace(".webp", "-128.webp")}


@router.get("/me/tokens")
async def list_tokens(actor: Actor = Depends(current_session), db=Depends(get_db)):
    rows = (await db.execute(text("""
        SELECT id,name,token_prefix,scopes,created_at,expires_at,last_used_at,revoked_at
        FROM community.user_api_tokens WHERE user_id=:id ORDER BY id DESC
    """), {"id": actor.id})).mappings().all()
    return [dict(row) for row in rows]


@router.post("/me/tokens", status_code=201)
async def create_token(body: TokenBody, actor: Actor = Depends(current_session), db=Depends(get_db)):
    active = int((await db.execute(text("""
        SELECT count(*) FROM community.user_api_tokens
        WHERE user_id=:id AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>now())
    """), {"id": actor.id})).scalar() or 0)
    if active >= 5:
        raise HTTPException(409, "每个账号最多保留 5 个有效 API Token")
    plain = f"hgs_{secrets.token_urlsafe(36)}"
    expires = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days else None
    )
    row = (await db.execute(text("""
        INSERT INTO community.user_api_tokens
          (user_id,name,token_hash,token_prefix,expires_at)
        VALUES (:user_id,:name,:token_hash,:prefix,:expires_at)
        RETURNING id,name,token_prefix,scopes,created_at,expires_at
    """), {
        "user_id": actor.id, "name": body.name.strip(),
        "token_hash": hashlib.sha256(plain.encode()).digest(), "prefix": plain[:12],
        "expires_at": expires,
    })).mappings().one()
    await db.commit()
    return {
        **dict(row),
        "token": plain,
        "api_base_url": f"{settings.public_base_url.rstrip('/')}/api",
        "agent_guide_url": f"{settings.public_base_url.rstrip('/')}/api/agent-guide",
        "openapi_url": f"{settings.public_base_url.rstrip('/')}/api/openapi.json",
        "agent_connection_text": agent_connection_text(plain),
    }


@router.delete("/me/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: int, actor: Actor = Depends(current_session), db=Depends(get_db)):
    result = await db.execute(text("""
        UPDATE community.user_api_tokens SET revoked_at=now()
        WHERE id=:token_id AND user_id=:user_id AND revoked_at IS NULL
    """), {"token_id": token_id, "user_id": actor.id})
    if result.rowcount == 0:
        raise HTTPException(404, "API Token 不存在")
    await db.commit()


@router.get("/{username}")
async def public_profile(username: str, actor: Actor | None = Depends(optional_actor), db=Depends(get_db)):
    viewer_id = actor.id if actor else 0
    row = (await db.execute(text("""
        SELECT u.id,u.username,u.display_name,u.bio,u.avatar_path,u.created_at,
          (SELECT count(*) FROM community.user_follows WHERE followed_user_id=u.id),
          (SELECT count(*) FROM community.user_follows WHERE follower_user_id=u.id),
          (SELECT count(*) FROM chemistry.reactions
           WHERE created_by_user_id=u.id AND visibility='public' AND moderation_status='visible'),
          EXISTS(SELECT 1 FROM community.user_follows
                 WHERE follower_user_id=:viewer AND followed_user_id=u.id)
        FROM community.users u WHERE lower(u.username)=lower(:username) AND u.status='active'
    """), {"username": username, "viewer": viewer_id})).fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    return {
        "id": row[0], "username": row[1], "display_name": row[2], "bio": row[3],
        "avatar_url": row[4], "created_at": row[5], "followers": row[6],
        "following": row[7], "public_reactions": row[8], "is_following": row[9],
        "is_me": bool(actor and row[0] == actor.id),
    }


async def relationship_page(
    username: str,
    relation: str,
    page: int,
    page_size: int,
    actor: Actor | None,
    db,
):
    target_id = (await db.execute(text("""
        SELECT id FROM community.users
        WHERE lower(username)=lower(:username) AND status='active'
    """), {"username": username})).scalar()
    if target_id is None:
        raise HTTPException(404, "用户不存在")

    if relation == "followers":
        target_column = "f.followed_user_id"
        person_column = "f.follower_user_id"
    elif relation == "following":
        target_column = "f.follower_user_id"
        person_column = "f.followed_user_id"
    else:
        raise ValueError("unsupported relationship")

    total = int((await db.execute(text(f"""
        SELECT count(*) FROM community.user_follows f
        JOIN community.users u ON u.id={person_column}
        WHERE {target_column}=:target_id AND u.status='active'
    """), {"target_id": target_id})).scalar() or 0)
    viewer_id = actor.id if actor else 0
    rows = (await db.execute(text(f"""
        SELECT u.username,u.display_name,u.bio,u.avatar_path AS avatar_url,
               EXISTS(
                 SELECT 1 FROM community.user_follows mine
                 WHERE mine.follower_user_id=:viewer_id AND mine.followed_user_id=u.id
               ) AS is_following,
               u.id=:viewer_id AS is_me
        FROM community.user_follows f
        JOIN community.users u ON u.id={person_column}
        WHERE {target_column}=:target_id AND u.status='active'
        ORDER BY f.created_at DESC,u.id
        LIMIT :page_size OFFSET :offset
    """), {
        "target_id": target_id,
        "viewer_id": viewer_id,
        "page_size": page_size,
        "offset": (page - 1) * page_size,
    })).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{username}/followers")
async def public_followers(
    username: str,
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(40, ge=1, le=100),
    actor: Actor | None = Depends(optional_actor),
    db=Depends(get_db),
):
    return await relationship_page(username, "followers", page, page_size, actor, db)


@router.get("/{username}/following")
async def public_following(
    username: str,
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(40, ge=1, le=100),
    actor: Actor | None = Depends(optional_actor),
    db=Depends(get_db),
):
    return await relationship_page(username, "following", page, page_size, actor, db)
