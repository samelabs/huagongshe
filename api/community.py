"""Small, review-first community layer for accounts and submissions."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from .config import settings
from .database import get_db
from .routes import CAS_RE, canonicalize_smiles

router = APIRouter(prefix="/community", tags=["community"])
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,30}$")


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str = Field(min_length=10, max_length=128)

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


class LoginBody(BaseModel):
    account: str
    password: str = Field(min_length=1, max_length=128)


class ChemicalSubmissionBody(BaseModel):
    smiles: str | None = Field(default=None, max_length=4000)
    cas: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=4000)


class ReactionSubmissionBody(BaseModel):
    reaction_smiles: str = Field(min_length=3, max_length=12000)
    reaction_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=10000)


class HelpPostBody(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=5, max_length=10000)


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


def public_user(row: Any) -> dict[str, Any]:
    return {"id": row[0], "username": row[1], "email": row[2], "role": row[3]}


async def current_user(
    token: str | None = Cookie(default=None, alias=settings.session_cookie), db=Depends(get_db)
):
    if not token:
        raise HTTPException(401, "请先登录")
    digest = hashlib.sha256(token.encode()).digest()
    row = (await db.execute(text("""
        SELECT u.id, u.username, u.email, u.role
        FROM community.sessions s
        JOIN community.users u ON u.id=s.user_id
        WHERE s.token_hash=:digest AND s.expires_at>now() AND u.status='active'
    """), {"digest": digest})).fetchone()
    if not row:
        raise HTTPException(401, "登录已过期")
    return public_user(row)


async def create_session(db: Any, response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_days)
    await db.execute(text("""
        INSERT INTO community.sessions(user_id, token_hash, expires_at)
        VALUES (:user_id, :digest, :expires)
    """), {"user_id": user_id, "digest": hashlib.sha256(token.encode()).digest(), "expires": expires})
    await db.commit()
    response.set_cookie(
        settings.session_cookie, token, max_age=settings.session_days * 86400,
        httponly=True, secure=True, samesite="lax", path="/",
    )


@router.post("/register", status_code=201)
async def register(body: RegisterBody, response: Response, db=Depends(get_db)):
    try:
        row = (await db.execute(text("""
            INSERT INTO community.users(username,email,password_hash)
            VALUES (:username,:email,:password_hash)
            RETURNING id,username,email,role
        """), {
            "username": body.username, "email": body.email,
            "password_hash": password_hash(body.password),
        })).one()
        await create_session(db, response, row[0])
        return public_user(row)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(409, "用户名或邮箱已被使用") from exc


@router.post("/login")
async def login(body: LoginBody, response: Response, db=Depends(get_db)):
    account = body.account.strip().lower()
    row = (await db.execute(text("""
        SELECT id,username,email,role,password_hash
        FROM community.users
        WHERE (lower(email)=:account OR lower(username)=:account) AND status='active'
    """), {"account": account})).fetchone()
    if not row or not password_matches(body.password, row[4]):
        raise HTTPException(401, "账号或密码不正确")
    await create_session(db, response, row[0])
    return public_user(row)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    token: str | None = Cookie(default=None, alias=settings.session_cookie),
    db=Depends(get_db),
):
    if token:
        await db.execute(text("DELETE FROM community.sessions WHERE token_hash=:digest"), {
            "digest": hashlib.sha256(token.encode()).digest()
        })
        await db.commit()
    response.delete_cookie(settings.session_cookie, path="/")


@router.get("/me")
async def me(user=Depends(current_user)):
    return user


@router.post("/chemical-submissions", status_code=201)
async def submit_chemical(
    body: ChemicalSubmissionBody, user=Depends(current_user), db=Depends(get_db)
):
    smiles = canonicalize_smiles(body.smiles or "") if body.smiles else None
    cas = body.cas.strip() if body.cas else None
    if body.smiles and not smiles:
        raise HTTPException(400, "SMILES 无法通过 RDKit 解析")
    if cas and not CAS_RE.fullmatch(cas):
        raise HTTPException(400, "CAS 格式不正确")
    if not smiles and not cas:
        raise HTTPException(400, "至少提交 SMILES 或 CAS")
    chemical_id = None
    if smiles:
        chemical_id = (await db.execute(text(
            "SELECT id FROM chemistry.chemicals WHERE smiles=:smiles AND mol IS NOT NULL LIMIT 1"
        ), {"smiles": smiles})).scalar()
    if chemical_id is None and cas:
        chemical_id = (await db.execute(text(
            "SELECT id FROM chemistry.chemicals WHERE cas_numbers @> ARRAY[:cas] LIMIT 1"
        ), {"cas": cas})).scalar()
    row = (await db.execute(text("""
        INSERT INTO community.chemical_submissions
          (user_id,chemical_id,submitted_smiles,submitted_cas,note)
        VALUES (:user_id,:chemical_id,:smiles,:cas,:note) RETURNING id,status,created_at
    """), {
        "user_id": user["id"], "chemical_id": chemical_id,
        "smiles": smiles, "cas": cas, "note": body.note,
    })).one()
    await db.commit()
    return {"id": row[0], "status": row[1], "created_at": row[2], "matched_chemical_id": chemical_id}


@router.post("/reaction-submissions", status_code=201)
async def submit_reaction(
    body: ReactionSubmissionBody, user=Depends(current_user), db=Depends(get_db)
):
    parts = body.reaction_smiles.strip().split(">")
    if len(parts) != 3 or not parts[0] or not parts[2]:
        raise HTTPException(400, "反应 SMILES 必须是 reactants>agents>products")
    for side in (parts[0], parts[2]):
        for smiles in filter(None, side.split(".")):
            if not canonicalize_smiles(smiles):
                raise HTTPException(400, f"无法解析结构：{smiles[:80]}")
    if body.reaction_id is not None:
        exists = (await db.execute(text(
            "SELECT 1 FROM chemistry.reactions WHERE id=:id"
        ), {"id": body.reaction_id})).scalar()
        if not exists:
            raise HTTPException(404, "需要补充的反应不存在")
    row = (await db.execute(text("""
        INSERT INTO community.reaction_submissions(user_id,reaction_id,reaction_smiles,note)
        VALUES (:user_id,:reaction_id,:reaction_smiles,:note) RETURNING id,status,created_at
    """), {
        "user_id": user["id"], "reaction_id": body.reaction_id,
        "reaction_smiles": body.reaction_smiles.strip(), "note": body.note,
    })).one()
    await db.commit()
    return {"id": row[0], "status": row[1], "created_at": row[2]}


@router.get("/my-submissions")
async def my_submissions(user=Depends(current_user), db=Depends(get_db)):
    chemicals = (await db.execute(text("""
        SELECT id,chemical_id,submitted_smiles,submitted_cas,note,status,created_at,updated_at
        FROM community.chemical_submissions WHERE user_id=:user_id ORDER BY id DESC LIMIT 100
    """), {"user_id": user["id"]})).mappings().all()
    reactions = (await db.execute(text("""
        SELECT id,reaction_id,reaction_smiles,note,status,created_at,updated_at
        FROM community.reaction_submissions WHERE user_id=:user_id ORDER BY id DESC LIMIT 100
    """), {"user_id": user["id"]})).mappings().all()
    return {"chemicals": [dict(row) for row in chemicals], "reactions": [dict(row) for row in reactions]}


@router.post("/chemicals/{chemical_id}/help", status_code=201)
async def create_help_post(
    chemical_id: int, body: HelpPostBody, user=Depends(current_user), db=Depends(get_db)
):
    exists = (await db.execute(text(
        "SELECT 1 FROM chemistry.chemicals WHERE id=:id"
    ), {"id": chemical_id})).scalar()
    if not exists:
        raise HTTPException(404, "化合物不存在")
    row = (await db.execute(text("""
        INSERT INTO community.reaction_help(user_id,chemical_id,title,body)
        VALUES (:user_id,:chemical_id,:title,:body) RETURNING id,created_at
    """), {
        "user_id": user["id"], "chemical_id": chemical_id,
        "title": body.title.strip(), "body": body.body.strip(),
    })).one()
    await db.commit()
    return {"id": row[0], "created_at": row[1]}


@router.get("/chemicals/{chemical_id}/help")
async def list_help_posts(chemical_id: int, db=Depends(get_db)):
    rows = (await db.execute(text("""
        SELECT h.id,h.title,h.body,h.created_at,u.username
        FROM community.reaction_help h JOIN community.users u ON u.id=h.user_id
        WHERE h.chemical_id=:id AND h.status='open' ORDER BY h.id DESC LIMIT 100
    """), {"id": chemical_id})).fetchall()
    return [{"id": r[0], "title": r[1], "body": r[2], "created_at": r[3], "username": r[4]} for r in rows]
