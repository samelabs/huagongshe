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

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .core.config import settings
from .core.database import get_db
from .core.rate_limit import enforce
from .core.security import (
    Actor, actor_payload, current_actor, current_session, public_or_actor,
    password_hash, password_matches,
)
from .schemas.users import RegisterBody, LoginBody, ProfileBody, TokenBody, PasswordBody

auth_router = APIRouter(prefix="/auth", tags=["users"])
router = APIRouter(prefix="/users", tags=["users"])
USERNAME_RE = re.compile(r"^[a-z0-9_]{4,30}$")

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


@auth_router.get("/check-username")
async def check_username(username: str = Query(min_length=4, max_length=30), db=Depends(get_db)):
    """注册时实时校验用户名是否可用。
    0904 ⑱: 枚举敞口 — 原无限流, 脚本可批量探测已注册用户名。
    匿名共享桶 30/min(BFF 后无真实 IP, 与 cas-search-fetch 同口径);
    超限 429, 注册表单降级为提交时校验(不阻塞正常使用)。"""
    await enforce("check-username", "global", 30, 60)
    if not USERNAME_RE.fullmatch(username):
        return {"available": False, "reason": "用户名仅支持 4–30 位小写字母、数字或下划线"}
    exists = (await db.execute(text(
        "SELECT 1 FROM community.users WHERE lower(username)=lower(:u) LIMIT 1"
    ), {"u": username})).fetchone()
    return {"available": not exists, "reason": "用户名已被使用" if exists else None}


@auth_router.post("/register", status_code=201)
async def register(body: RegisterBody, response: Response, db=Depends(get_db)):
    # 注册界=全局宽松上限: 只防批量灌号; 真实流量(个位数/天)永远不可见.
    # per-IP 对代理池无效(B2 后应用层也拿不到真实 IP), 不做地址维度.
    await enforce("register", "global", 60, 3600)
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
async def login(body: LoginBody, response: Response, db=Depends(get_db)):
    account = body.account.strip().lower()
    # 限流键=账号本身: 换 IP(代理池)无效; 换账号打的是廉价未命中查询, 不触发 scrypt.
    # 真实账号的猜解被账号桶封死 → scrypt(~50ms/次) CPU 消耗有界.
    await enforce("login", hashlib.sha256(account.encode()).hexdigest()[:24], 15, 900)
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
    try:
        await db.execute(text("""
            UPDATE community.users
            SET display_name=:display_name,
                bio=:bio,
                email=:email,
                location=:location,
                institution=:institution,
                title=:title,
                website=:website,
                orcid=:orcid,
                updated_at=now()
            WHERE id=:id
        """), {**body.model_dump(), "id": actor.id})
        await db.commit()
    except IntegrityError as exc:
        # 0904 敞口收口: email 唯一索引(community_users_email_uidx)冲突此前
        # 未处理直接 500(对照 register 路径同款异常已有 409)。精确判定:
        # 只把 email 撞号转 409; 其余约束冲突(display_name/bio CHECK 已被
        # pydantic Field 等值挡住, 理论不可达)原样抛, 不吞成误导性 409。
        await db.rollback()
        if "community_users_email_uidx" in str(getattr(exc, "orig", "")) or "community_users_email_uidx" in str(exc):
            raise HTTPException(409, "邮箱已被其他账号占用") from exc
        raise
    return body.model_dump()


@router.post("/me/password", status_code=204)
async def change_password(
    body: PasswordBody, response: Response, actor: Actor = Depends(current_session), db=Depends(get_db)
):
    # scrypt 验证昂贵: 认证会话重复错误 current_password = CPU 放大,
    # 简单 actor bucket (LOW-PATCH, 与 login account bucket 同风格)
    await enforce("password-change", str(actor.id), 10, 900)
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
    # revoke = 物理 DELETE(2026-08-31 终局): 不保留 soft-revoke 两套语义
    await db.execute(text("DELETE FROM community.user_api_tokens WHERE user_id=:id"), {"id": actor.id})
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


@router.delete("/me/avatar", status_code=204)
async def delete_avatar(actor: Actor = Depends(current_session), db=Depends(get_db)):
    old_path = (await db.execute(text(
        "SELECT avatar_path FROM community.users WHERE id=:id"
    ), {"id": actor.id})).scalar()
    await db.execute(text("""
        UPDATE community.users
        SET avatar_path=NULL,avatar_version=NULL,updated_at=now()
        WHERE id=:id
    """), {"id": actor.id})
    await db.commit()
    if old_path and old_path.startswith("/uploads/avatars/"):
        user_dir = os.path.join(settings.avatar_root, str(actor.id))
        old_name = os.path.basename(old_path)
        for name in (old_name, old_name.replace(".webp", "-128.webp")):
            candidate = os.path.join(user_dir, name)
            if os.path.exists(candidate):
                os.unlink(candidate)


@router.get("/me/tokens")
async def list_tokens(response: Response, actor: Actor = Depends(current_session), db=Depends(get_db)):
    # 响应含 token_plain(secret): 明确禁缓存, 不依赖 CDN/浏览器默认
    response.headers["Cache-Control"] = "private, no-store"
    rows = (await db.execute(text("""
        SELECT id,name,token_prefix,scopes,created_at,expires_at,last_used_at,token_plain
        FROM community.user_api_tokens
        WHERE user_id=:id AND revoked_at IS NULL
        ORDER BY id DESC
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
          (user_id,name,token_hash,token_prefix,token_plain,expires_at)
        VALUES (:user_id,:name,:token_hash,:prefix,:plain,:expires_at)
        RETURNING id,name,token_prefix,scopes,created_at,expires_at
    """), {
        "user_id": actor.id, "name": body.name.strip(),
        "token_hash": hashlib.sha256(plain.encode()).digest(), "prefix": plain[:12],
        "plain": plain, "expires_at": expires,
    })).mappings().one()
    await db.commit()
    # P2 边界归一: Token 创建只返回 credential 与 token metadata。
    # api_base_url / agent_guide_url / agent_connection_text 已删除(前端零真实消费者,
    # onboarding 耦合由 /guide 与 /mcp-guide 平级入口承担)。
    return {
        **dict(row),
        "token": plain,
    }


@router.delete("/me/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: int, actor: Actor = Depends(current_session), db=Depends(get_db)):
    # 2026-08-31 用户裁定: 撤销=物理删除, 留存无意义; 列表也不再展示已撤销
    result = await db.execute(text("""
        DELETE FROM community.user_api_tokens
        WHERE id=:token_id AND user_id=:user_id
    """), {"token_id": token_id, "user_id": actor.id})
    if result.rowcount == 0:
        raise HTTPException(404, "API Token 不存在")
    await db.commit()


@router.get("/{username}")
async def public_profile(username: str, actor: Actor | None = Depends(public_or_actor), db=Depends(get_db)):
    viewer_id = actor.id if actor else 0
    row = (await db.execute(text("""
        SELECT u.id,u.username,u.display_name,u.bio,u.avatar_path,u.created_at,
          u.location,u.institution,u.title,u.website,u.orcid,u.email,
          (SELECT count(*) FROM community.user_follows WHERE followed_user_id=u.id),
          (SELECT count(*) FROM community.user_follows WHERE follower_user_id=u.id),
          (SELECT count(*) FROM chemistry.reactions
           WHERE created_by_user_id=u.id AND visibility='public' AND moderation_status='visible'),
          EXISTS(SELECT 1 FROM community.user_follows
                 WHERE follower_user_id=:viewer AND followed_user_id=u.id),
          EXISTS(SELECT 1 FROM community.user_follows
                 WHERE follower_user_id=u.id AND followed_user_id=:viewer)
        FROM community.users u WHERE lower(u.username)=lower(:username) AND u.status='active'
    """), {"username": username, "viewer": viewer_id})).fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    return {
        "id": row[0], "username": row[1], "display_name": row[2], "bio": row[3],
        "avatar_url": row[4], "created_at": row[5],
        "location": row[6], "institution": row[7], "title": row[8],
        "website": row[9], "orcid": row[10],
        "followers": row[12], "following": row[13], "public_reactions": row[14],
        "is_following": row[15],
        "is_followed_by": bool(row[16]) if viewer_id else False,
        "is_mutual": bool(row[15] and row[16]) if viewer_id else False,
        "is_me": bool(actor and row[0] == actor.id),
        # Email is private: only the profile owner's own view may read it,
        # so the settings form can prefill without a separate endpoint.
        **({"email": row[11]} if actor and row[0] == actor.id else {}),
    }


