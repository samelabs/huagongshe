"""Authenticated, review-first community workflow for core chemistry data."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from rdkit import Chem
from rdkit.Chem import Descriptors, rdChemReactions, rdMolDescriptors
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .cache import cache_delete
from .config import settings
from .database import get_db
from .chemistry import CAS_RE, canonicalize_smiles

router = APIRouter(prefix="/community", tags=["community"])
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,30}$")
REVIEW_ROLES = {"editor", "admin"}
PARTICIPANT_ROLES = ("REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT")


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
    account: str
    password: str = Field(min_length=1, max_length=128)


class ChemicalSubmissionBody(BaseModel):
    smiles: str | None = Field(default=None, max_length=4000)
    cas: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=4000)


class ReactionParticipantBody(BaseModel):
    role: Literal["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"]
    smiles: str = Field(min_length=1, max_length=4000)
    yield_percent: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def product_yield_only(self):
        if self.yield_percent is not None and self.role != "PRODUCT":
            raise ValueError("只有产物可以填写收率")
        return self


class ReactionSubmissionBody(BaseModel):
    reaction_id: int | None = Field(default=None, gt=0)
    participants: list[ReactionParticipantBody] = Field(min_length=2, max_length=100)
    procedure_details: str = Field(min_length=10, max_length=30000)
    conditions_detail: str | None = Field(default=None, max_length=10000)
    temperature_value: float | None = None
    temperature_unit: Literal["CELSIUS", "KELVIN"] | None = None
    duration_value: float | None = Field(default=None, gt=0)
    duration_unit: Literal["MINUTE", "HOUR", "DAY"] | None = None
    ph: float | None = Field(default=None, ge=0, le=14)
    atmosphere: str | None = Field(default=None, max_length=120)
    pressure_value: float | None = Field(default=None, gt=0)
    pressure_unit: str | None = Field(default=None, max_length=40)
    safety_notes: str | None = Field(default=None, max_length=10000)
    doi: str | None = Field(default=None, max_length=300)
    patent: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def validate_reaction(self):
        roles = {participant.role for participant in self.participants}
        if "REACTANT" not in roles or "PRODUCT" not in roles:
            raise ValueError("至少需要一个反应物和一个产物")
        if (self.temperature_value is None) != (self.temperature_unit is None):
            raise ValueError("温度数值和单位必须同时填写")
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("反应时间数值和单位必须同时填写")
        if (self.pressure_value is None) != (self.pressure_unit is None):
            raise ValueError("压力数值和单位必须同时填写")
        if self.source_url and not re.fullmatch(r"https?://\S+", self.source_url.strip()):
            raise ValueError("来源链接必须以 http:// 或 https:// 开头")
        return self


class ReviewBody(BaseModel):
    decision: Literal["accept", "reject"]
    review_note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def rejection_needs_reason(self):
        if self.decision == "reject" and not (self.review_note or "").strip():
            raise ValueError("拒绝提交时必须填写审核说明")
        return self


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


def cleaned(value: str | None) -> str | None:
    result = (value or "").strip()
    return result or None


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


async def reviewer(user=Depends(current_user)):
    if user["role"] not in REVIEW_ROLES:
        raise HTTPException(403, "没有审核权限")
    return user


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


def reaction_smiles_from_participants(participants: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for participant in participants:
        grouped[participant["role"]].append(participant["canonical_smiles"])
    reactants = ".".join(grouped["REACTANT"])
    agents = ".".join(
        smiles
        for role in ("REAGENT", "CATALYST", "SOLVENT")
        for smiles in grouped[role]
    )
    products = ".".join(grouped["PRODUCT"])
    result = f"{reactants}>{agents}>{products}"
    try:
        reaction = rdChemReactions.ReactionFromSmarts(result, useSmiles=True)
    except Exception as exc:
        raise HTTPException(400, "反应结构无法通过 RDKit 解析") from exc
    if reaction is None:
        raise HTTPException(400, "反应结构无法通过 RDKit 解析")
    return result


def chemical_properties(smiles: str) -> dict[str, Any]:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(400, "化合物结构无法通过 RDKit 解析")
    try:
        inchikey = Chem.MolToInchiKey(mol) or None
    except Exception:
        inchikey = None
    return {
        "molecular_formula": rdMolDescriptors.CalcMolFormula(mol),
        "average_mass": float(Descriptors.MolWt(mol)),
        "monoisotopic_mass": float(Descriptors.ExactMolWt(mol)),
        "inchikey": inchikey,
    }


async def resolve_or_create_chemical(
    db: Any, smiles: str, preferred_name: str | None = None, cas: str | None = None
) -> int:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:smiles, 0))"), {"smiles": smiles})
    chemical_id = (await db.execute(text("""
        SELECT id FROM chemistry.chemicals
        WHERE smiles=:smiles AND mol IS NOT NULL ORDER BY id LIMIT 1
    """), {"smiles": smiles})).scalar()
    if chemical_id is not None:
        if preferred_name or cas:
            await db.execute(text("""
                UPDATE chemistry.chemicals
                SET preferred_name=COALESCE(preferred_name,:name),
                    cas_numbers=CASE
                      WHEN CAST(:cas AS text) IS NULL
                        OR cas_numbers @> ARRAY[CAST(:cas AS text)] THEN cas_numbers
                      ELSE array_append(COALESCE(cas_numbers,ARRAY[]::text[]),CAST(:cas AS text))
                    END,
                    updated_at=now()
                WHERE id=:id
            """), {"id": chemical_id, "name": preferred_name, "cas": cas})
        return int(chemical_id)

    props = chemical_properties(smiles)
    chemical_id = int((await db.execute(text("""
        INSERT INTO chemistry.chemicals
          (smiles,preferred_name,cas_numbers,molecular_formula,average_mass,
           monoisotopic_mass,inchikey,mol,morgan_bfp,morgan_sfp,created_at,updated_at)
        VALUES
          (:smiles,:name,CASE WHEN CAST(:cas AS text) IS NULL
                             THEN NULL ELSE ARRAY[CAST(:cas AS text)] END,
           :molecular_formula,:average_mass,:monoisotopic_mass,:inchikey,
           mol_from_smiles(:smiles),morganbv_fp(mol_from_smiles(:smiles)),
           morgan_fp(mol_from_smiles(:smiles)),now(),now())
        RETURNING id
    """), {"smiles": smiles, "name": preferred_name, "cas": cas, **props})).scalar_one())
    await db.execute(text("""
        UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
        WHERE metric='chemicals'
    """))
    return chemical_id


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
    except IntegrityError as exc:
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
    cas = cleaned(body.cas)
    name = cleaned(body.name)
    if body.smiles and not smiles:
        raise HTTPException(400, "SMILES 无法通过 RDKit 解析")
    if cas and not CAS_RE.fullmatch(cas):
        raise HTTPException(400, "CAS 格式不正确")
    if not smiles and not cas:
        raise HTTPException(400, "至少提交 SMILES 或 CAS")
    chemical_id = None
    if smiles:
        chemical_id = (await db.execute(text("""
            SELECT id FROM chemistry.chemicals
            WHERE smiles=:smiles AND mol IS NOT NULL ORDER BY id LIMIT 1
        """), {"smiles": smiles})).scalar()
    if chemical_id is None and cas:
        chemical_id = (await db.execute(text(
            "SELECT id FROM chemistry.chemicals WHERE cas_numbers @> ARRAY[:cas] ORDER BY id LIMIT 1"
        ), {"cas": cas})).scalar()
    row = (await db.execute(text("""
        INSERT INTO community.chemical_submissions
          (user_id,chemical_id,submitted_smiles,submitted_cas,submitted_name,note)
        VALUES (:user_id,:chemical_id,:smiles,:cas,:name,:note) RETURNING id,status,created_at
    """), {
        "user_id": user["id"], "chemical_id": chemical_id, "smiles": smiles,
        "cas": cas, "name": name, "note": cleaned(body.note),
    })).one()
    await db.commit()
    return {"id": row[0], "status": row[1], "created_at": row[2], "matched_chemical_id": chemical_id}


@router.post("/reaction-submissions", status_code=201)
async def submit_reaction(
    body: ReactionSubmissionBody, user=Depends(current_user), db=Depends(get_db)
):
    participants: list[dict[str, Any]] = []
    for position, item in enumerate(body.participants):
        canonical = canonicalize_smiles(item.smiles)
        if not canonical:
            raise HTTPException(400, f"无法解析结构：{item.smiles[:80]}")
        participants.append({
            "position": position, "role": item.role,
            "submitted_smiles": item.smiles.strip(), "canonical_smiles": canonical,
            "yield_percent": item.yield_percent,
        })
    reaction_smiles = reaction_smiles_from_participants(participants)
    if body.reaction_id is not None:
        exists = (await db.execute(text(
            "SELECT 1 FROM chemistry.reactions WHERE id=:id"
        ), {"id": body.reaction_id})).scalar()
        if not exists:
            raise HTTPException(404, "需要补充或纠正的反应不存在")
    row = (await db.execute(text("""
        INSERT INTO community.reaction_submissions
          (user_id,reaction_id,reaction_smiles,procedure_details,conditions_detail,
           temperature_value,temperature_unit,duration_value,duration_unit,ph,
           atmosphere,pressure_value,pressure_unit,safety_notes,doi,patent,source_url,note)
        VALUES
          (:user_id,:reaction_id,:reaction_smiles,:procedure_details,:conditions_detail,
           :temperature_value,:temperature_unit,:duration_value,:duration_unit,:ph,
           :atmosphere,:pressure_value,:pressure_unit,:safety_notes,:doi,:patent,:source_url,:note)
        RETURNING id,status,created_at
    """), {
        "user_id": user["id"], "reaction_id": body.reaction_id,
        "reaction_smiles": reaction_smiles,
        "procedure_details": body.procedure_details.strip(),
        "conditions_detail": cleaned(body.conditions_detail),
        "temperature_value": body.temperature_value, "temperature_unit": body.temperature_unit,
        "duration_value": body.duration_value, "duration_unit": body.duration_unit,
        "ph": body.ph, "atmosphere": cleaned(body.atmosphere),
        "pressure_value": body.pressure_value, "pressure_unit": cleaned(body.pressure_unit),
        "safety_notes": cleaned(body.safety_notes), "doi": cleaned(body.doi),
        "patent": cleaned(body.patent), "source_url": cleaned(body.source_url),
        "note": cleaned(body.note),
    })).one()
    for participant in participants:
        await db.execute(text("""
            INSERT INTO community.reaction_submission_participants
              (submission_id,position,role,submitted_smiles,canonical_smiles,yield_percent)
            VALUES (:submission_id,:position,:role,:submitted_smiles,:canonical_smiles,:yield_percent)
        """), {"submission_id": row[0], **participant})
    await db.commit()
    return {"id": row[0], "status": row[1], "created_at": row[2], "reaction_smiles": reaction_smiles}


@router.get("/my-submissions")
async def my_submissions(user=Depends(current_user), db=Depends(get_db)):
    chemicals = (await db.execute(text("""
        SELECT id,chemical_id,submitted_smiles,submitted_cas,submitted_name,note,status,
               review_note,reviewed_at,created_at,updated_at
        FROM community.chemical_submissions WHERE user_id=:user_id ORDER BY id DESC LIMIT 100
    """), {"user_id": user["id"]})).mappings().all()
    reactions = (await db.execute(text("""
        SELECT id,reaction_id,reaction_smiles,procedure_details,note,status,
               review_note,reviewed_at,created_at,updated_at
        FROM community.reaction_submissions WHERE user_id=:user_id ORDER BY id DESC LIMIT 100
    """), {"user_id": user["id"]})).mappings().all()
    return {"chemicals": [dict(row) for row in chemicals], "reactions": [dict(row) for row in reactions]}


@router.get("/admin/submissions")
async def review_queue(
    status: Literal["pending", "accepted", "rejected"] = Query("pending"),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(reviewer), db=Depends(get_db),
):
    chemicals = (await db.execute(text("""
        SELECT s.id,s.user_id,u.username,s.chemical_id,s.submitted_smiles,s.submitted_cas,
               s.submitted_name,s.note,s.status,s.review_note,s.reviewed_at,s.created_at
        FROM community.chemical_submissions s
        JOIN community.users u ON u.id=s.user_id
        WHERE s.status=:status ORDER BY s.id LIMIT :limit
    """), {"status": status, "limit": limit})).mappings().all()
    reactions = (await db.execute(text("""
        SELECT s.id,s.user_id,u.username,s.reaction_id,s.reaction_smiles,
               s.procedure_details,s.conditions_detail,s.temperature_value,s.temperature_unit,
               s.duration_value,s.duration_unit,s.ph,s.atmosphere,s.pressure_value,
               s.pressure_unit,s.safety_notes,s.doi,s.patent,s.source_url,s.note,
               s.status,s.review_note,s.reviewed_at,s.created_at
        FROM community.reaction_submissions s
        JOIN community.users u ON u.id=s.user_id
        WHERE s.status=:status ORDER BY s.id LIMIT :limit
    """), {"status": status, "limit": limit})).mappings().all()
    reaction_items = [dict(row) for row in reactions]
    ids = [item["id"] for item in reaction_items]
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        rows = (await db.execute(text("""
            SELECT submission_id,position,role,submitted_smiles,canonical_smiles,
                   chemical_id,yield_percent
            FROM community.reaction_submission_participants
            WHERE submission_id=ANY(:ids) ORDER BY submission_id,position
        """), {"ids": ids})).mappings().all()
        for row in rows:
            item = dict(row)
            grouped[item.pop("submission_id")].append(item)
    for item in reaction_items:
        item["participants"] = grouped[item["id"]]
    return {"chemicals": [dict(row) for row in chemicals], "reactions": reaction_items}


@router.post("/admin/chemical-submissions/{submission_id}/review")
async def review_chemical_submission(
    submission_id: int, body: ReviewBody, user=Depends(reviewer), db=Depends(get_db)
):
    submission = (await db.execute(text("""
        SELECT * FROM community.chemical_submissions WHERE id=:id FOR UPDATE
    """), {"id": submission_id})).mappings().fetchone()
    if not submission:
        raise HTTPException(404, "化合物提交不存在")
    if submission["status"] != "pending":
        raise HTTPException(409, "该提交已经审核")
    if body.decision == "reject":
        await db.execute(text("""
            UPDATE community.chemical_submissions
            SET status='rejected',reviewer_id=:reviewer_id,review_note=:note,
                reviewed_at=now(),updated_at=now() WHERE id=:id
        """), {"id": submission_id, "reviewer_id": user["id"], "note": cleaned(body.review_note)})
        await db.commit()
        return {"id": submission_id, "status": "rejected"}

    chemical_id = submission["chemical_id"]
    if chemical_id is not None:
        exists = (await db.execute(text(
            "SELECT 1 FROM chemistry.chemicals WHERE id=:id"
        ), {"id": chemical_id})).scalar()
        if not exists:
            chemical_id = None
    if chemical_id is None:
        if not submission["submitted_smiles"]:
            raise HTTPException(409, "CAS 未匹配现有化合物，需补充可验证结构后再接受")
        chemical_id = await resolve_or_create_chemical(
            db, submission["submitted_smiles"], submission["submitted_name"], submission["submitted_cas"]
        )
    else:
        await db.execute(text("""
            UPDATE chemistry.chemicals
            SET preferred_name=COALESCE(preferred_name,:name),
                cas_numbers=CASE
                  WHEN CAST(:cas AS text) IS NULL
                    OR cas_numbers @> ARRAY[CAST(:cas AS text)] THEN cas_numbers
                  ELSE array_append(COALESCE(cas_numbers,ARRAY[]::text[]),CAST(:cas AS text))
                END,
                updated_at=now()
            WHERE id=:id
        """), {
            "id": chemical_id, "name": submission["submitted_name"], "cas": submission["submitted_cas"]
        })
    await db.execute(text("""
        UPDATE community.chemical_submissions
        SET status='accepted',chemical_id=:chemical_id,reviewer_id=:reviewer_id,
            review_note=:note,reviewed_at=now(),updated_at=now() WHERE id=:id
    """), {
        "id": submission_id, "chemical_id": chemical_id,
        "reviewer_id": user["id"], "note": cleaned(body.review_note),
    })
    await db.commit()
    await cache_delete("v3:stats:exact")
    return {"id": submission_id, "status": "accepted", "chemical_id": chemical_id}


@router.post("/admin/reaction-submissions/{submission_id}/review")
async def review_reaction_submission(
    submission_id: int, body: ReviewBody, user=Depends(reviewer), db=Depends(get_db)
):
    submission = (await db.execute(text("""
        SELECT * FROM community.reaction_submissions WHERE id=:id FOR UPDATE
    """), {"id": submission_id})).mappings().fetchone()
    if not submission:
        raise HTTPException(404, "反应提交不存在")
    if submission["status"] != "pending":
        raise HTTPException(409, "该提交已经审核")
    if body.decision == "reject":
        await db.execute(text("""
            UPDATE community.reaction_submissions
            SET status='rejected',reviewer_id=:reviewer_id,review_note=:note,
                reviewed_at=now(),updated_at=now() WHERE id=:id
        """), {"id": submission_id, "reviewer_id": user["id"], "note": cleaned(body.review_note)})
        await db.commit()
        return {"id": submission_id, "status": "rejected"}

    participants = (await db.execute(text("""
        SELECT id,position,role,canonical_smiles,yield_percent
        FROM community.reaction_submission_participants
        WHERE submission_id=:id ORDER BY position FOR UPDATE
    """), {"id": submission_id})).mappings().all()
    if not participants:
        raise HTTPException(409, "该提交没有结构化参与物")
    resolved: list[dict[str, Any]] = []
    for participant in participants:
        chemical_id = await resolve_or_create_chemical(db, participant["canonical_smiles"])
        await db.execute(text("""
            UPDATE community.reaction_submission_participants SET chemical_id=:chemical_id WHERE id=:id
        """), {"id": participant["id"], "chemical_id": chemical_id})
        resolved.append({**dict(participant), "chemical_id": chemical_id})

    reaction_id = submission["reaction_id"]
    is_new = reaction_id is None
    if is_new:
        reaction_id = (await db.execute(text("""
            INSERT INTO chemistry.reactions(id,reaction_smiles,reaction)
            VALUES (nextval('chemistry.reactions_id_seq'),:reaction_smiles,
                    reaction_from_smiles(:reaction_input)) RETURNING id
        """), {
            "reaction_smiles": submission["reaction_smiles"],
            "reaction_input": submission["reaction_smiles"],
        })).scalar_one()
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
            WHERE metric='reactions'
        """))
    else:
        await db.execute(text("""
            UPDATE chemistry.reactions
            SET reaction_smiles=:reaction_smiles,
                reaction=reaction_from_smiles(:reaction_input),updated_at=now()
            WHERE id=:id
        """), {
            "id": reaction_id, "reaction_smiles": submission["reaction_smiles"],
            "reaction_input": submission["reaction_smiles"],
        })

    await db.execute(text(
        "DELETE FROM chemistry.reaction_chemicals WHERE reaction_id=:reaction_id"
    ), {"reaction_id": reaction_id})
    relationships = Counter((item["chemical_id"], item["role"]) for item in resolved)
    for (chemical_id, role), occurrence_count in relationships.items():
        await db.execute(text("""
            INSERT INTO chemistry.reaction_chemicals
              (reaction_id,chemical_id,role,occurrence_count)
            VALUES (:reaction_id,:chemical_id,:role,:occurrence_count)
        """), {
            "reaction_id": reaction_id, "chemical_id": chemical_id,
            "role": role, "occurrence_count": occurrence_count,
        })
    await db.execute(text("""
        UPDATE community.reaction_submissions
        SET status='accepted',reaction_id=:reaction_id,reviewer_id=:reviewer_id,
            review_note=:note,reviewed_at=now(),updated_at=now() WHERE id=:id
    """), {
        "id": submission_id, "reaction_id": reaction_id,
        "reviewer_id": user["id"], "note": cleaned(body.review_note),
    })
    await db.commit()
    await cache_delete("v3:stats:exact")
    return {"id": submission_id, "status": "accepted", "reaction_id": reaction_id, "created": is_new}


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
