"""The single write path for web users and their AI Agents."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from rdkit import Chem
from rdkit.Chem import Descriptors, rdChemReactions, rdMolDescriptors
from sqlalchemy import text

from .cache import cache_delete
from .chemistry import canonicalize_smiles, normalize_doi
from .config import settings
from .database import get_db
from .rate_limit import enforce
from .security import Actor, current_actor, require_scope

router = APIRouter(tags=["reactions"])
ROLES = ("REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT")


class ParticipantBody(BaseModel):
    role: Literal["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"]
    smiles: str = Field(min_length=1, max_length=4000)
    occurrence_count: int = Field(default=1, ge=1, le=20)
    amount_value: float | None = Field(default=None, ge=0)
    amount_unit: str | None = Field(default=None, max_length=40)
    equivalents: float | None = Field(default=None, ge=0)
    concentration_value: float | None = Field(default=None, ge=0)
    concentration_unit: str | None = Field(default=None, max_length=40)
    yield_percent: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_fields(self):
        if self.yield_percent is not None and self.role != "PRODUCT":
            raise ValueError("只有产物可以填写收率")
        if (self.amount_value is None) != (self.amount_unit is None):
            raise ValueError("投料数值和单位必须同时填写")
        if (self.concentration_value is None) != (self.concentration_unit is None):
            raise ValueError("浓度数值和单位必须同时填写")
        return self


class ReactionBody(BaseModel):
    visibility: Literal["public", "private"]
    participants: list[ParticipantBody] = Field(min_length=2, max_length=100)
    procedure_details: str | None = Field(default=None, max_length=30000)
    conditions_detail: str | None = Field(default=None, max_length=10000)
    temperature_value: float | None = None
    temperature_unit: Literal["CELSIUS", "KELVIN"] | None = None
    duration_value: float | None = Field(default=None, gt=0)
    duration_unit: Literal["MINUTE", "HOUR", "DAY"] | None = None
    ph: float | None = Field(default=None, ge=0, le=14)
    atmosphere: str | None = Field(default=None, max_length=120)
    pressure_value: float | None = Field(default=None, gt=0)
    pressure_unit: str | None = Field(default=None, max_length=40)
    workup_details: str | None = Field(default=None, max_length=10000)
    safety_notes: str | None = Field(default=None, max_length=10000)
    source_type: Literal["self", "doi", "patent", "database", "url", "other"]
    doi: str | None = Field(default=None, max_length=300)
    patent: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=1000)
    source_citation: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=10000)

    @field_validator(
        "procedure_details", "conditions_detail", "atmosphere", "pressure_unit",
        "workup_details", "safety_notes", "patent", "source_url",
        "source_citation", "note",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        result = (value or "").strip()
        return result or None

    @field_validator("doi")
    @classmethod
    def clean_doi(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = normalize_doi(value)
        if not normalized:
            raise ValueError("DOI 格式不正确")
        return normalized

    @model_validator(mode="after")
    def validate_reaction(self):
        roles = {item.role for item in self.participants}
        if "REACTANT" not in roles or "PRODUCT" not in roles:
            raise ValueError("至少需要一个反应物和一个产物")
        if (self.temperature_value is None) != (self.temperature_unit is None):
            raise ValueError("温度数值和单位必须同时填写")
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("反应时间数值和单位必须同时填写")
        if (self.pressure_value is None) != (self.pressure_unit is None):
            raise ValueError("压力数值和单位必须同时填写")
        if self.source_url and not self.source_url.startswith(("http://", "https://")):
            raise ValueError("来源链接必须以 http:// 或 https:// 开头")
        requirements = {
            "doi": self.doi,
            "patent": self.patent,
            "url": self.source_url,
            "database": self.source_citation,
            "other": self.source_citation,
        }
        if self.source_type in requirements and not requirements[self.source_type]:
            raise ValueError(f"来源类型 {self.source_type} 缺少对应的来源信息")
        return self


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


async def resolve_or_create_chemical(db, smiles: str) -> tuple[int, bool]:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:smiles,0))"), {"smiles": smiles})
    chemical_id = (await db.execute(text("""
        SELECT id FROM chemistry.chemicals
        WHERE smiles=:smiles AND mol IS NOT NULL ORDER BY id LIMIT 1
    """), {"smiles": smiles})).scalar()
    if chemical_id is not None:
        return int(chemical_id), False
    props = chemical_properties(smiles)
    chemical_id = int((await db.execute(text("""
        INSERT INTO chemistry.chemicals
          (smiles,molecular_formula,average_mass,monoisotopic_mass,inchikey,
           mol,morgan_bfp,morgan_sfp,created_at,updated_at)
        VALUES
          (:smiles,:molecular_formula,:average_mass,:monoisotopic_mass,:inchikey,
           mol_from_smiles(:smiles),morganbv_fp(mol_from_smiles(:smiles)),
           morgan_fp(mol_from_smiles(:smiles)),now(),now())
        RETURNING id
    """), {"smiles": smiles, **props})).scalar_one())
    await db.execute(text("""
        UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
        WHERE metric='chemicals'
    """))
    return chemical_id, True


def canonical_participants(body: ReactionBody) -> tuple[list[dict[str, Any]], str]:
    participants: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    grouped: dict[str, list[str]] = defaultdict(list)
    for position, item in enumerate(body.participants):
        canonical = canonicalize_smiles(item.smiles)
        if not canonical:
            raise HTTPException(400, f"无法解析参与物结构：{item.smiles[:80]}")
        key = (item.role, canonical)
        if key in seen:
            raise HTTPException(409, "同一化合物和角色请合并为一项，并填写出现次数")
        seen.add(key)
        record = {"position": position, "canonical_smiles": canonical, **item.model_dump(exclude={"smiles"})}
        participants.append(record)
        grouped[item.role].extend([canonical] * item.occurrence_count)
    reaction_smiles = ".".join(grouped["REACTANT"]) + ">" + ".".join(
        value for role in ("REAGENT", "CATALYST", "SOLVENT") for value in grouped[role]
    ) + ">" + ".".join(grouped["PRODUCT"])
    try:
        reaction = rdChemReactions.ReactionFromSmarts(reaction_smiles, useSmiles=True)
    except Exception as exc:
        raise HTTPException(400, "反应结构无法通过 RDKit 解析") from exc
    if reaction is None or not reaction.GetNumReactantTemplates() or not reaction.GetNumProductTemplates():
        raise HTTPException(400, "反应结构无法通过 RDKit 解析")
    return participants, reaction_smiles


def reaction_values(body: ReactionBody) -> dict[str, Any]:
    return body.model_dump(exclude={"participants"})


async def resolve_participants(db, participants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    resolved: list[dict[str, Any]] = []
    created: list[int] = []
    for participant in participants:
        chemical_id, is_new = await resolve_or_create_chemical(db, participant["canonical_smiles"])
        resolved.append({**participant, "chemical_id": chemical_id})
        if is_new:
            created.append(chemical_id)
    return resolved, created


async def write_relationships(db, reaction_id: int, participants: list[dict[str, Any]]) -> None:
    for item in participants:
        await db.execute(text("""
            INSERT INTO chemistry.reaction_chemicals
              (reaction_id,chemical_id,role,occurrence_count,amount_value,amount_unit,
               equivalents,concentration_value,concentration_unit,yield_percent)
            VALUES
              (:reaction_id,:chemical_id,:role,:occurrence_count,:amount_value,:amount_unit,
               :equivalents,:concentration_value,:concentration_unit,:yield_percent)
        """), {"reaction_id": reaction_id, **item})


async def notify_new_reaction(db, actor_id: int, reaction_id: int) -> None:
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,reaction_id,dedupe_key)
        SELECT follower_user_id,'new_reaction',:actor_id,:reaction_id,
               'new-reaction:' || follower_user_id::text || ':' || :reaction_id_text
        FROM community.user_follows
        WHERE followed_user_id=:actor_id AND follower_user_id<>:actor_id
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "actor_id": actor_id, "reaction_id": reaction_id, "reaction_id_text": str(reaction_id),
    })


async def reaction_response(db, reaction_id: int, created_chemicals: list[int] | None = None) -> dict[str, Any]:
    row = (await db.execute(text("""
        SELECT id,reaction_smiles,visibility,created_by_user_id,created_via,created_at,updated_at
        FROM chemistry.reactions WHERE id=:id
    """), {"id": reaction_id})).fetchone()
    participants = (await db.execute(text("""
        SELECT chemical_id,role,occurrence_count,amount_value,amount_unit,equivalents,
               concentration_value,concentration_unit,yield_percent
        FROM chemistry.reaction_chemicals WHERE reaction_id=:id
        ORDER BY CASE role WHEN 'REACTANT' THEN 1 WHEN 'REAGENT' THEN 2 WHEN 'CATALYST' THEN 3
                           WHEN 'SOLVENT' THEN 4 ELSE 5 END,chemical_id
    """), {"id": reaction_id})).mappings().all()
    return {
        "id": row[0], "hrid": f"HRID {row[0]}", "reaction_smiles": row[1],
        "visibility": row[2], "created_by_user_id": row[3], "created_via": row[4],
        "created_at": row[5], "updated_at": row[6],
        "participants": [dict(item) for item in participants],
        "created_chemical_ids": created_chemicals or [],
        "url": f"https://huagongshe.com/reaction/{row[0]}",
    }


@router.post("/reactions/validate")
async def validate_reaction(body: ReactionBody, actor: Actor = Depends(current_actor)):
    require_scope(actor, "reaction:write")
    await enforce("reaction-validate", str(actor.id), 20, 60)
    participants, reaction_smiles = canonical_participants(body)
    return {
        "valid": True, "reaction_smiles": reaction_smiles,
        "participants": [
            {"role": item["role"], "canonical_smiles": item["canonical_smiles"],
             "occurrence_count": item["occurrence_count"]}
            for item in participants
        ],
    }


@router.post("/reactions", status_code=201)
async def create_reaction(
    body: ReactionBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    require_scope(actor, "reaction:write")
    await enforce("reaction-write-minute", str(actor.id), settings.api_reaction_write_limit_per_minute, 60)
    await enforce("reaction-write-day", str(actor.id), settings.api_reaction_write_limit_per_day, 86400)
    if actor.auth_kind == "agent" and not idempotency_key:
        raise HTTPException(400, "使用 API Token 提交必须提供 Idempotency-Key")
    if idempotency_key and len(idempotency_key) > 200:
        raise HTTPException(400, "Idempotency-Key 不能超过 200 个字符")
    if idempotency_key:
        existing = (await db.execute(text("""
            SELECT id FROM chemistry.reactions
            WHERE created_by_user_id=:user_id AND idempotency_key=:key
        """), {"user_id": actor.id, "key": idempotency_key})).scalar()
        if existing is not None:
            return await reaction_response(db, int(existing))

    participants, reaction_smiles = canonical_participants(body)
    resolved, created_chemicals = await resolve_participants(db, participants)
    values = reaction_values(body)
    reaction_id = int((await db.execute(text("""
        INSERT INTO chemistry.reactions
          (id,reaction_smiles,reaction,created_by_user_id,visibility,created_via,
           procedure_details,conditions_detail,temperature_value,temperature_unit,
           duration_value,duration_unit,ph,atmosphere,pressure_value,pressure_unit,
           workup_details,safety_notes,source_type,doi,patent,source_url,source_citation,
           note,idempotency_key)
        VALUES
          (nextval('chemistry.reactions_id_seq'),:reaction_smiles,
           CAST(:reaction_input AS public.reaction),:user_id,:visibility,:created_via,
           :procedure_details,:conditions_detail,:temperature_value,:temperature_unit,
           :duration_value,:duration_unit,:ph,:atmosphere,:pressure_value,:pressure_unit,
           :workup_details,:safety_notes,:source_type,:doi,:patent,:source_url,:source_citation,
           :note,:idempotency_key)
        RETURNING id
    """), {
        **values, "reaction_smiles": reaction_smiles, "reaction_input": reaction_smiles,
        "user_id": actor.id, "created_via": "agent" if actor.auth_kind == "agent" else "web",
        "idempotency_key": idempotency_key,
    })).scalar_one())
    await write_relationships(db, reaction_id, resolved)
    if body.visibility == "public":
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
            WHERE metric='reactions'
        """))
        await notify_new_reaction(db, actor.id, reaction_id)
    await db.commit()
    await cache_delete("v1:stats:exact")
    return await reaction_response(db, reaction_id, created_chemicals)


@router.put("/reactions/{reaction_id}")
async def update_reaction(
    reaction_id: int, body: ReactionBody, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    if actor.auth_kind == "agent":
        raise HTTPException(403, "API Token 当前不开放反应编辑，请使用网页登录会话")
    await enforce("reaction-write-minute", str(actor.id), settings.api_reaction_write_limit_per_minute, 60)
    current = (await db.execute(text("""
        SELECT created_by_user_id,visibility FROM chemistry.reactions WHERE id=:id FOR UPDATE
    """), {"id": reaction_id})).fetchone()
    if not current:
        raise HTTPException(404, "反应不存在")
    if current[0] != actor.id:
        raise HTTPException(403, "只能维护自己创建的反应")
    participants, reaction_smiles = canonical_participants(body)
    resolved, created_chemicals = await resolve_participants(db, participants)
    values = reaction_values(body)
    await db.execute(text("""
        UPDATE chemistry.reactions SET
          reaction_smiles=:reaction_smiles,reaction=CAST(:reaction_input AS public.reaction),
          visibility=:visibility,procedure_details=:procedure_details,
          conditions_detail=:conditions_detail,temperature_value=:temperature_value,
          temperature_unit=:temperature_unit,duration_value=:duration_value,
          duration_unit=:duration_unit,ph=:ph,atmosphere=:atmosphere,
          pressure_value=:pressure_value,pressure_unit=:pressure_unit,
          workup_details=:workup_details,safety_notes=:safety_notes,source_type=:source_type,
          doi=:doi,patent=:patent,source_url=:source_url,source_citation=:source_citation,
          note=:note,updated_at=now()
        WHERE id=:id
    """), {**values, "id": reaction_id, "reaction_smiles": reaction_smiles, "reaction_input": reaction_smiles})
    await db.execute(text("DELETE FROM chemistry.reaction_chemicals WHERE reaction_id=:id"), {"id": reaction_id})
    await write_relationships(db, reaction_id, resolved)
    if body.visibility == "private":
        await db.execute(text("DELETE FROM community.reaction_follows WHERE reaction_id=:id"), {"id": reaction_id})
        if current[1] == "public":
            await db.execute(text("""
                UPDATE chemistry.statistics SET exact_count=greatest(exact_count-1,0),calculated_at=now()
                WHERE metric='reactions'
            """))
    elif current[1] == "private":
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
            WHERE metric='reactions'
        """))
        await notify_new_reaction(db, actor.id, reaction_id)
    await db.commit()
    if current[1] != body.visibility:
        await cache_delete("v1:stats:exact")
    return await reaction_response(db, reaction_id, created_chemicals)


@router.delete("/reactions/{reaction_id}", status_code=204)
async def delete_reaction(reaction_id: int, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    if actor.auth_kind == "agent":
        raise HTTPException(403, "API Token 当前不开放反应删除，请使用网页登录会话")
    record = (await db.execute(text("""
        SELECT created_by_user_id,visibility,moderation_status
        FROM chemistry.reactions WHERE id=:id FOR UPDATE
    """), {"id": reaction_id})).fetchone()
    if record is None:
        raise HTTPException(404, "反应不存在")
    owner = record[0]
    if owner is None:
        raise HTTPException(403, "系统导入反应不能由用户删除")
    if int(owner) != actor.id:
        raise HTTPException(403, "只能删除自己创建的反应")
    await db.execute(text("DELETE FROM chemistry.reactions WHERE id=:id"), {"id": reaction_id})
    if record[1] == "public" and record[2] == "visible":
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=greatest(exact_count-1,0),calculated_at=now()
            WHERE metric='reactions'
        """))
    await db.commit()
    await cache_delete("v1:stats:exact")


@router.get("/users/me/reactions")
async def my_reactions(
    visibility: Literal["all", "public", "private"] = Query("all"),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(20, ge=1, le=50),
    actor: Actor = Depends(current_actor), db=Depends(get_db),
):
    offset = (page - 1) * page_size
    params = {
        "user_id": actor.id, "visibility": visibility, "limit": page_size,
        "offset": offset, "window": offset + page_size,
    }
    if visibility == "all":
        # Keep each branch on (created_by_user_id, visibility, id DESC). Without
        # these bounded branches PostgreSQL may walk the 2.4M-row primary key
        # backwards to satisfy ORDER BY before it applies the owner filter.
        query = text("""
            WITH owned AS MATERIALIZED (
              (SELECT id,reaction_smiles,visibility,moderation_status,created_at,updated_at
               FROM chemistry.reactions
               WHERE created_by_user_id=:user_id AND visibility='public'
               ORDER BY id DESC LIMIT :window)
              UNION ALL
              (SELECT id,reaction_smiles,visibility,moderation_status,created_at,updated_at
               FROM chemistry.reactions
               WHERE created_by_user_id=:user_id AND visibility='private'
               ORDER BY id DESC LIMIT :window)
            )
            SELECT r.*,
              (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=r.id) AS followers
            FROM owned r ORDER BY id DESC LIMIT :limit OFFSET :offset
        """)
    else:
        query = text("""
            SELECT r.id,r.reaction_smiles,r.visibility,r.moderation_status,r.created_at,r.updated_at,
              (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=r.id) AS followers
            FROM chemistry.reactions r
            WHERE r.created_by_user_id=:user_id AND r.visibility=:visibility
            ORDER BY r.id DESC LIMIT :limit OFFSET :offset
        """)
    rows = (await db.execute(query, params)).mappings().all()
    count_rows = (await db.execute(text("""
        SELECT visibility,count(*)
        FROM chemistry.reactions
        WHERE created_by_user_id=:user_id
        GROUP BY visibility
    """), {"user_id": actor.id})).all()
    counts = {"public": 0, "private": 0}
    for value, count in count_rows:
        counts[value] = int(count)
    return {
        "items": [dict(row) for row in rows], "counts": {**counts, "all": sum(counts.values())},
        "page": page, "page_size": page_size,
    }


@router.get("/users/{username}/reactions")
async def user_reactions(
    username: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
    db=Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT r.id,r.reaction_smiles,r.visibility,r.created_at,r.updated_at,
          (SELECT count(*) FROM community.reaction_follows WHERE reaction_id=r.id) AS followers
        FROM chemistry.reactions r JOIN community.users u ON u.id=r.created_by_user_id
        WHERE lower(u.username)=lower(:username) AND u.status='active'
          AND r.visibility='public' AND r.moderation_status='visible'
        ORDER BY r.id DESC LIMIT :limit OFFSET :offset
    """), {"username": username, "limit": page_size, "offset": (page-1)*page_size})).mappings().all()
    return [dict(row) for row in rows]


@router.get("/agent-guide", tags=["agent"])
async def agent_guide():
    return {
        "api_version": settings.api_version,
        "purpose": "帮助用户查询化学数据并提交属于该用户的结构化反应",
        "api_base_url": "https://huagongshe.com/api",
        "openapi_url": "https://huagongshe.com/api/openapi.json",
        "help_url": "https://huagongshe.com/guide",
        "optional_skill_url": "https://huagongshe.com/skills/huagongshe-reaction-publisher/SKILL.md",
        "authentication": "Authorization: Bearer <用户创建的 API Token>",
        "navigation": [
            {"purpose": "查询化合物或反应", "method": "GET", "path": "/api/search"},
            {"purpose": "校验反应草稿", "method": "POST", "path": "/api/reactions/validate"},
            {"purpose": "发布已确认的反应", "method": "POST", "path": "/api/reactions"},
            {"purpose": "读取用户反应库", "method": "GET", "path": "/api/users/me/reactions"},
        ],
        "workflow": [
            "读取用户提供的网页、文档、图片或文本并保留来源证据",
            "只整理明确事实；结构有歧义或必要字段缺失时向用户确认",
            "生成结构化草稿并确认 visibility=public 或 private",
            "调用 POST /api/reactions/validate",
            "用户确认后携带唯一 Idempotency-Key 调用 POST /api/reactions",
            "向用户返回 HRID、页面 URL、可见性和新建 HCID",
        ],
        "rules": [
            "本入口和 OpenAPI 即可完成接入；Skill 仅用于为支持技能的 AI 固定行为约束。",
            "提交前应查询并核对参与物；系统最终仍会按标准结构匹配或创建 HCID。",
            "不得编造 SMILES、来源、条件、收率或实验过程；未知值应省略。",
            "至少提供一个反应物、一个产物和明确的 source_type。",
            "公开提交前必须确认用户希望 visibility=public；否则使用 private。",
            "正式提交必须发送唯一 Idempotency-Key，重试时复用同一个值。",
            "先调用 POST /api/reactions/validate，再调用 POST /api/reactions。",
            "API Token 当前只用于查询、验证和创建；编辑、可见性调整与删除由用户在网页完成。",
        ],
        "source_types": {
            "self": "用户本人实验", "doi": "必须提供 doi", "patent": "必须提供 patent",
            "url": "必须提供 source_url", "database": "必须提供 source_citation",
            "other": "必须提供 source_citation",
        },
        "operation_ids": [
            "GET /api/search", "GET /api/chemicals/{id}", "GET /api/reactions/{id}",
            "POST /api/reactions/validate", "POST /api/reactions",
            "GET /api/users/me/reactions",
        ],
        "ownership": {
            "created_reaction": "直接归入 Token 所属用户的反应仓库",
            "public": "可被所有人查询和关注",
            "private": "仅创建者网页登录后可见",
            "maintenance": "创建者可在网页编辑、切换可见性或删除",
        },
        "rate_limits": {
            "queries_per_minute": settings.api_query_limit_per_minute,
            "structure_queries_per_minute": settings.api_structure_limit_per_minute,
            "reaction_writes_per_minute": settings.api_reaction_write_limit_per_minute,
            "reaction_writes_per_day": settings.api_reaction_write_limit_per_day,
        },
    }
