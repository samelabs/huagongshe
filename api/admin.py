"""Platform governance: accounts, visibility, configuration and dashboard."""

from __future__ import annotations

import json
import re
import shutil
import asyncio
import hashlib
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .core.cache import cache_delete
from .core.config import settings
from .core.database import get_db
from .core.security import Actor, current_session
from .schemas.admin import UserStatusBody, UserRoleBody, ModerationBody, WorkerCreateBody, WorkerPatchBody, SkillVisibilityBody, CategoryBody, WORKER_SCOPES

router = APIRouter(prefix="/admin", tags=["administration"], include_in_schema=False)


async def admin(actor: Actor = Depends(current_session)) -> Actor:
    if actor.role != "admin":
        raise HTTPException(403, "没有平台管理权限")
    return actor


def _validated_scopes(scopes: list[str]) -> list[str]:
    unknown = [s for s in scopes if s not in WORKER_SCOPES]
    if unknown:
        raise HTTPException(400, f"未知的任务族: {', '.join(unknown)}(可用: {', '.join(WORKER_SCOPES)})")
    return sorted(set(scopes))


@router.get("/workers")
async def list_workers(
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    """Worker 客户端清单(不含 token hash)。"""
    rows = (await db.execute(text("""
        SELECT worker_id,display_name,scopes,max_lease_jobs,enabled,
               created_at,last_seen_at,disabled_at
        FROM maintenance.worker_clients ORDER BY worker_id
    """))).mappings().all()
    return [dict(row) for row in rows]


@router.post("/workers", status_code=201)
async def create_worker(
    body: WorkerCreateBody,
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    """签发新 Worker 凭据. 明文 token 仅本响应返回一次, 库内只存 hash. """
    scopes = _validated_scopes(body.scopes)
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode()).hexdigest()
    try:
        await db.execute(text("""
            INSERT INTO maintenance.worker_clients
            (worker_id,display_name,token_hash,token_prefix,scopes,max_lease_jobs)
            VALUES (:worker_id,:display_name,decode(:digest,'hex'),:prefix,
                    CAST(:scopes AS text[]),:max_lease_jobs)
        """), {
            "worker_id": body.worker_id,
            "display_name": body.display_name,
            "digest": digest,
            "prefix": token[:8],
            "scopes": scopes,
            "max_lease_jobs": body.max_lease_jobs,
        })
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"worker_id 已存在: {body.worker_id}")
    return {
        "worker_id": body.worker_id,
        "display_name": body.display_name,
        "scopes": scopes,
        "max_lease_jobs": body.max_lease_jobs,
        "token": token,  # 一次性明文, 之后不可再取
        "env": {
            "HGS_WORKAPI_URL": "http://127.0.0.1:8000",
            "HGS_WORKER_ID": body.worker_id,
            "HGS_WORKER_TOKEN": token,
        },
    }


@router.patch("/workers/{worker_id}")
async def patch_worker(
    worker_id: str,
    body: WorkerPatchBody,
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    """编辑 Worker 元数据/停权. 停权后 worker 下次 lease 即 401; 不提供 DELETE(保留审计轨迹)."""
    scopes = _validated_scopes(body.scopes) if body.scopes is not None else None
    result = (await db.execute(text("""
        UPDATE maintenance.worker_clients
        SET display_name=coalesce(:display_name,display_name),
            scopes=coalesce(CAST(:scopes AS text[]),scopes),
            max_lease_jobs=coalesce(:max_lease_jobs,max_lease_jobs),
            enabled=coalesce(:enabled,enabled),
            disabled_at=CASE WHEN coalesce(:enabled,enabled)=false AND disabled_at IS NULL
                        THEN now() ELSE disabled_at END
        WHERE worker_id=:worker_id
        RETURNING worker_id,display_name,scopes,max_lease_jobs,enabled,created_at,last_seen_at,disabled_at
    """), {
        "worker_id": worker_id,
        "display_name": body.display_name,
        "scopes": scopes,
        "max_lease_jobs": body.max_lease_jobs,
        "enabled": body.enabled,
    })).mappings().fetchone()
    if not result:
        raise HTTPException(404, f"worker 不存在: {worker_id}")
    await db.commit()
    return dict(result)


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


# ── 技能治理 ──────────────────────────────────────────────

@router.get("/skills")
async def list_all_skills(
    q: str = Query("", max_length=120),
    visibility: Literal["all", "public", "private"] = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    conditions = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if q.strip():
        conditions.append("(s.slug ILIKE :q OR s.title ILIKE :q OR u.username ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if visibility != "all":
        conditions.append("s.visibility=:vis")
        params["vis"] = visibility
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    total = (await db.execute(text(f"""
        SELECT count(*) FROM community.skills s JOIN community.users u ON u.id=s.owner_id {where}
    """), params)).scalar() or 0
    rows = (await db.execute(text(f"""
        SELECT s.id,s.slug,s.title,s.description,s.category,s.origin,s.visibility,
               s.has_scripts,s.file_count,s.size_bytes,s.created_at,s.updated_at,
               s.published_at,s.publish_note,
               u.username,u.display_name
        FROM community.skills s JOIN community.users u ON u.id=s.owner_id
        {where}
        ORDER BY s.updated_at DESC, s.id DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    # owner 嵌套结构与 /api/skills 全站契约对齐（skills.py _row_to_skill）
    items = []
    for r in rows:
        d = dict(r)
        d["owner"] = {"username": d.pop("username"), "display_name": d.pop("display_name")}
        items.append(d)
    return {"total": int(total), "items": items}


@router.patch("/skills/{skill_id}/visibility")
async def set_skill_visibility(
    skill_id: int, body: SkillVisibilityBody,
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    """公开态唯一入口：受控管理动作，审计字段随动。"""
    note = (body.note or "").strip() or None
    if note and len(note) > 200:
        raise HTTPException(400, "发布备注不能超过 200 字")
    result = await db.execute(text("""
        UPDATE community.skills SET
          visibility=:vis,
          origin=CASE WHEN :vis='public' AND origin='user' THEN 'official' ELSE origin END,
          published_by=:actor, published_at=CASE WHEN :vis='public' THEN now() ELSE published_at END,
          publish_note=:note, updated_at=now()
        WHERE id=:id
    """), {"id": skill_id, "vis": body.visibility, "actor": actor.id, "note": note})
    if result.rowcount == 0:
        raise HTTPException(404, "技能不存在")
    await db.commit()
    return {"id": skill_id, "visibility": body.visibility}


@router.delete("/skills/{skill_id}")
async def admin_delete_skill(
    skill_id: int, actor: Actor = Depends(admin), db=Depends(get_db),
):
    row = (await db.execute(text("""
        SELECT id FROM community.skills WHERE id=:id
    """), {"id": skill_id})).fetchone()
    if row is None:
        raise HTTPException(404, "技能不存在")
    await db.execute(text("DELETE FROM community.skills WHERE id=:id"), {"id": skill_id})
    await db.commit()
    await asyncio.to_thread(shutil.rmtree, Path(settings.skill_root) / str(skill_id), True)
    return {"id": skill_id, "deleted": True}


@router.get("/skill-categories")
async def list_categories(actor: Actor = Depends(admin), db=Depends(get_db)):
    rows = (await db.execute(text("""
        SELECT id,name,abbr,color,sort_order,active,
               (SELECT count(*) FROM community.skills s WHERE s.category=c.name) AS skill_count
        FROM community.skill_categories c ORDER BY sort_order, id
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.post("/skill-categories")
async def create_category(
    body: CategoryBody, actor: Actor = Depends(admin), db=Depends(get_db),
):
    name = body.name.strip()
    abbr = body.abbr.strip().upper()
    color = body.color.strip().lower()
    if not (1 <= len(name) <= 40):
        raise HTTPException(400, "分类名长度 1-40")
    if not re.fullmatch(r"[A-Z]{1,4}", abbr):
        raise HTTPException(400, "缩写为 1-4 个英文字母")
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        raise HTTPException(400, "色值格式 #rrggbb")
    dup = (await db.execute(text(
        "SELECT 1 FROM community.skill_categories WHERE name=:n"
    ), {"n": name})).scalar()
    if dup is not None:
        raise HTTPException(409, "分类已存在")
    row = (await db.execute(text("""
        INSERT INTO community.skill_categories (name,abbr,color,sort_order,active)
        VALUES (:name,:abbr,:color,:sort,:active) RETURNING id
    """), {"name": name, "abbr": abbr, "color": color, "sort": body.sort_order, "active": body.active})).fetchone()
    await db.commit()
    return {"id": int(row[0]), "name": name, "abbr": abbr, "color": color}


@router.patch("/skill-categories/{category_id}")
async def update_category(
    category_id: int, body: CategoryBody,
    actor: Actor = Depends(admin), db=Depends(get_db),
):
    """改名/改色/排序/停用；停用不物理删，存量引用不悬空。"""
    name = body.name.strip()
    abbr = body.abbr.strip().upper()
    color = body.color.strip().lower()
    if not (1 <= len(name) <= 40):
        raise HTTPException(400, "分类名长度 1-40")
    if not re.fullmatch(r"[A-Z]{1,4}", abbr):
        raise HTTPException(400, "缩写为 1-4 个英文字母")
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        raise HTTPException(400, "色值格式 #rrggbb")
    row = await db.execute(text("""
        SELECT name FROM community.skill_categories WHERE id=:id
    """), {"id": category_id})
    old_name = row.scalar_one_or_none()
    if old_name is None:
        raise HTTPException(404, "分类不存在")
    if old_name != name:
        dup = await db.execute(text("""
            SELECT 1 FROM community.skill_categories
            WHERE name=:name AND id<>:id LIMIT 1
        """), {"id": category_id, "name": name})
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(409, "分类名已存在")
        # 先同步存量技能引用（读旧名），再改字典，两步顺序不可颠倒
        await db.execute(text("""
            UPDATE community.skills SET category=:name
            WHERE category=:old_name
        """), {"name": name, "old_name": old_name})
    await db.execute(text("""
        UPDATE community.skill_categories
        SET name=:name,abbr=:abbr,color=:color,sort_order=:sort,active=:active
        WHERE id=:id
    """), {"id": category_id, "name": name, "abbr": abbr, "color": color,
           "sort": body.sort_order, "active": body.active})
    await db.commit()
    return {"id": category_id, "name": name, "active": body.active}


# ── 仪表盘 ──────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(actor: Actor = Depends(admin), db=Depends(get_db)):
    """全局运行状态概览。"""
    row = (await db.execute(text("""
        SELECT
          (SELECT count(*) FROM community.users),
          (SELECT count(*) FROM community.users WHERE created_at >= current_date),
          (SELECT count(*) FROM community.users WHERE created_at >= date_trunc('week', current_date)),
          (SELECT count(*) FROM community.sessions WHERE expires_at > now()),
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


# ── 数据管道运行时 ────────────────────────────────────────

@router.get("/pipeline")
async def pipeline(actor: Actor = Depends(admin), db=Depends(get_db)):
    """数据链运行时(0902 重构): CB/PB 分链独立展示, 语义对齐新机制
    — queued/leased/error 三态, error=留痕占位, 吞吐=数据层真实落库。"""
    now_iso = (await db.execute(text("SELECT now()"))).scalar().isoformat()

    async def chain_counts(table: str) -> dict:
        rows = (await db.execute(text(f"""
            SELECT status, count(*) FROM maintenance.{table} GROUP BY status
        """))).fetchall()
        d = {r[0]: int(r[1]) for r in rows}
        return {"queued": d.get("queued", 0), "leased": d.get("leased", 0),
                "error": d.get("error", 0)}

    async def error_buckets(table: str) -> dict:
        rows = (await db.execute(text(f"""
            SELECT last_error_code, count(*) FROM maintenance.{table}
            WHERE status='error' GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """))).fetchall()
        return {r[0] or "unknown": int(r[1]) for r in rows}

    # ── CB 链 ──
    cb_queue = await chain_counts("cas_jobs")
    cb_errors = await error_buckets("cas_jobs")
    cb_tp_rows = (await db.execute(text("""
        SELECT last_status, count(*) FROM chemistry.chemical_cb
        WHERE fetched_at >= current_date GROUP BY 1
    """))).fetchall()
    cb_tp = {r[0]: int(r[1]) for r in cb_tp_rows}
    cb_throughput = {"ok": cb_tp.get("ok", 0), "not_found": cb_tp.get("not_found", 0),
                     "total": cb_tp.get("ok", 0) + cb_tp.get("not_found", 0)}
    cb_rate = int((await db.execute(text("""
        SELECT count(*) FROM chemistry.chemical_cb
        WHERE fetched_at >= now() - interval '1 hour'
    """))).scalar())
    cb_latest_at = (await db.execute(text("""
        SELECT max(fetched_at) FROM chemistry.chemical_cb
    """))).scalar()
    loc_rows = (await db.execute(text("""
        SELECT locale, last_status, count(*) FROM chemistry.chemical_cb
        WHERE fetched_at >= current_date
        GROUP BY locale, last_status ORDER BY locale
    """))).fetchall()
    loc_map: dict[str, dict[str, int]] = {}
    for locale, status, n in loc_rows:
        cur = loc_map.setdefault(locale, {"ok": 0, "not_found": 0})
        if status in cur:
            cur[status] = int(n)
    cb_locales = [{"locale": k, **v} for k, v in loc_map.items()]

    # ── PB 链 ──
    pb_queue = await chain_counts("pubchem_jobs")
    pb_errors = await error_buckets("pubchem_jobs")
    pb_total = int((await db.execute(text("""
        SELECT count(*) FROM chemistry.chemical_pubchem
        WHERE fetched_at >= current_date
    """))).scalar())
    pb_throughput = {"ok": pb_total, "not_found": -1, "total": pb_total}
    pb_rate = int((await db.execute(text("""
        SELECT count(*) FROM chemistry.chemical_pubchem
        WHERE fetched_at >= now() - interval '1 hour'
    """))).scalar())
    pb_latest_at = (await db.execute(text("""
        SELECT max(fetched_at) FROM chemistry.chemical_pubchem
    """))).scalar()

    # ── 闸门(redis db1, 0902 口径) ──
    gates = {}
    try:
        from .core.cache import get_cache
        import time as _time
        redis = await get_cache()
        for ch in ("pubchem", "cb"):
            streak = await redis.get(f"gate:{ch}:streak")
            until = await redis.get(f"gate:{ch}:silent_until")
            remaining = max(0.0, float(until) - _time.time()) if until else 0.0
            gates[ch] = {
                "streak": int(streak) if streak else 0,
                "silent": remaining > 0,
                "silent_remaining_s": int(remaining),
            }
    except Exception:
        gates = {"pubchem": None, "cb": None}

    # ── worker 在线状态 ──
    workers = (await db.execute(text("""
        SELECT worker_id, display_name, enabled, last_seen_at
        FROM maintenance.worker_clients ORDER BY worker_id
    """))).fetchall()

    # ── 供应商(CB 链产物) ──
    sup = (await db.execute(text("""
        SELECT
          (SELECT count(*) FROM chemistry.chemical_supplier_listing WHERE fetched_at >= current_date),
          (SELECT count(DISTINCT chemical_id) FROM chemistry.chemical_supplier_listing WHERE fetched_at >= current_date),
          (SELECT count(*) FROM chemistry.chemical_supplier_listing),
          (SELECT count(DISTINCT chemical_id) FROM chemistry.chemical_supplier_listing),
          (SELECT count(*) FROM chemistry.chemical_supplier_profile)
    """))).fetchone()

    return {
        "supplier": {
            "today_rows": int(sup[0]), "today_chemicals": int(sup[1]),
            "total_rows": int(sup[2]), "total_chemicals": int(sup[3]),
            "profiles": int(sup[4]),
        },
        "cb": {
            "queue": cb_queue, "error_buckets": cb_errors,
            "throughput": cb_throughput, "rate_1h": cb_rate,
            "latest_at": cb_latest_at.isoformat() if cb_latest_at else None,
            "locales_today": cb_locales,
        },
        "pb": {
            "queue": pb_queue, "error_buckets": pb_errors,
            "throughput": pb_throughput, "rate_1h": pb_rate,
            "latest_at": pb_latest_at.isoformat() if pb_latest_at else None,
        },
        "gates": gates,
        "workers": [
            {"worker_id": r[0], "display_name": r[1], "enabled": r[2],
             "last_seen_at": r[3].isoformat() if r[3] else None}
            for r in workers
        ],
        "generated_at": now_iso,
    }


@router.post("/pipeline/{chain}/errors/revive")
async def revive_errors(
    chain: str,
    actor: Actor = Depends(admin),
    db=Depends(get_db),
):
    """error 行手动复活(0902): 一键把该链全部 error 态翻回 queued。
    语义同闸门复活(gate_unlock), 管理员手动触发通道。"""
    if chain not in ("cb", "pb"):
        raise HTTPException(400, "chain 必须是 cb 或 pb")
    table = "cas_jobs" if chain == "cb" else "pubchem_jobs"
    result = (await db.execute(text(f"""
        UPDATE maintenance.{table}
        SET status='queued', updated_at=now()
        WHERE status='error'
    """))).rowcount
    await db.commit()
    return {"chain": chain, "revived": result}


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
    await db.execute(text("""
        INSERT INTO community.system_config (namespace, key, value, updated_at)
        VALUES (:ns, :key, CAST(:value AS jsonb), now())
        ON CONFLICT (namespace, key) DO UPDATE SET value = CAST(:value AS jsonb), updated_at = now()
    """), {"ns": namespace, "key": key, "value": json.dumps(body)})
    await db.commit()
    await cache_delete("config:public:all")
    return {"namespace": namespace, "key": key, "value": body}

