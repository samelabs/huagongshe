"""Platform governance: accounts, visibility, configuration and dashboard."""

from __future__ import annotations

import json
import re
import shutil
import asyncio
import hashlib
from datetime import datetime
import time as _time
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import logging

from .core.cache import cache_delete
from .core.config import settings
from .core.database import get_db
from .core.security import Actor, current_session
from .schemas.admin import UserStatusBody, UserRoleBody, ModerationBody, WorkerCreateBody, WorkerPatchBody, SkillVisibilityBody, CategoryBody, WORKER_SCOPES

router = APIRouter(prefix="/admin", tags=["administration"], include_in_schema=False)
logger = logging.getLogger("api.admin")


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
        # revoke = 物理 DELETE(与用户侧 password change 同一语义), 不留 soft-revoke
        await db.execute(text("DELETE FROM community.user_api_tokens WHERE user_id=:id"), {"id": user_id})
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

# A1 (0912) 统计缓存治理:
# - last-known-good: 刷新失败继续返回旧 snapshot, 标 stale (绝不因刷新失败 500)
# - 单飞: asyncio.Lock 防并发请求同时触发相同重扫描(全表扫 ~3s, 值得挡)
# - 返回带 generated_at/stale/age_seconds, 前端如实显示统计时间
_PIPELINE_STATS_CACHE: dict = {}      # {"v": snapshot, "ts": monotonic, "wall": iso}
_PIPELINE_STATS_TTL = 60.0            # 秒: 管理端"总量"类精确统计的新鲜度
_PIPELINE_STATS_LOCK = asyncio.Lock()  # 单飞: 同一进程内只允许一个刷新在跑


class _SectionFailure(RuntimeError):
    """optional section 刷新失败 —— 降级, 不炸整页。携带 section 名。"""

    def __init__(self, section: str, exc: Exception):
        super().__init__(f"{section}: {exc!r}")
        self.section = section
        self.exc = exc


async def _scan_critical(db) -> tuple:
    cb_locales = [
        {"locale": r[0], "today": int(r[1]), "total": int(r[2]), "last_1h": int(r[3])}
        for r in (await db.execute(text("""
            SELECT locale,
                   count(*) FILTER (WHERE fetched_at >= current_date),
                   count(*),
                   count(*) FILTER (WHERE fetched_at >= now() - interval '1 hour')
            FROM chemistry.chemical_cb GROUP BY locale
        """))).fetchall()
    ]
    pb_today, pb_last_1h, pb_total_rows = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE fetched_at >= current_date),
               count(*) FILTER (WHERE fetched_at >= now() - interval '1 hour'),
               count(*)
        FROM chemistry.chemical_pubchem
    """))).fetchone()
    return cb_locales, int(pb_today), int(pb_last_1h), int(pb_total_rows)

async def _scan_supplier(db) -> dict:
    sup = (await db.execute(text("""
        SELECT
          count(*) FILTER (WHERE fetched_at >= current_date),
          count(DISTINCT chemical_id) FILTER (WHERE fetched_at >= current_date),
          count(*),
          count(DISTINCT chemical_id),
          (SELECT count(*) FROM chemistry.chemical_supplier_profile),
          (SELECT count(*) FROM chemistry.chemical_supplier_profile WHERE fetched_at >= current_date)
        FROM chemistry.chemical_supplier_listing
    """))).fetchone()
    return {"today_rows": int(sup[0]), "today_chemicals": int(sup[1]),
            "total_rows": int(sup[2]), "total_chemicals": int(sup[3]),
            "profiles": int(sup[4]), "today_profiles": int(sup[5])}

async def _scan_seed(db) -> dict:
    # CB 上游账本 (89万 cb_number 种子) —— 按 status 索引扫描, 快
    seed = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE status = 'ACCEPTED'),
               count(*) FILTER (WHERE status = 'ENQUEUED'),
               count(*) FILTER (WHERE status = 'AMBIGUOUS')
        FROM ingestion.chemicalbook_seed
    """))).fetchone()
    return {"accepted": int(seed[0]), "enqueued": int(seed[1]), "ambiguous": int(seed[2])}

async def _scan_negative(db) -> dict:
    # CB 负面观测账本 (无数据不落主表, 只落这里)
    neg = (await db.execute(text("""
        SELECT count(*), count(*) FILTER (WHERE observed_at >= current_date)
        FROM maintenance.cb_negative_observations
    """))).fetchone()
    return {"total": int(neg[0]), "today": int(neg[1])}



# ── A2 数据治理 (0912): 只读诊断, 独立端点, 不塞主 pipeline ──

@router.get("/pipeline/governance")
async def pipeline_governance(actor: Actor = Depends(admin), db=Depends(get_db)):
    """较慢治理指标(样本+缓存 300s)。主 /pipeline 保持轻。"""
    from .services.pipeline_governance import get_governance
    return await get_governance(db)


@router.get("/pipeline/governance/drilldown/{key}")
async def pipeline_governance_drilldown(
    key: str, actor: Actor = Depends(admin), db=Depends(get_db),
):
    """关键异常数字 → 样本列表(LIMIT 50)。无持久化证据的 key 明确拒绝。"""
    from .services.pipeline_governance import DRILL_UNSUPPORTED, drill_down
    if key in DRILL_UNSUPPORTED:
        raise HTTPException(400, f"当前没有持久化证据或该指标无 drill-down 语义: {DRILL_UNSUPPORTED[key]}")
    return await drill_down(db, key)


@router.get("/pipeline")
async def pipeline(actor: Actor = Depends(admin), db=Depends(get_db)):
    """数据管道运行时(0911 定稿口径): CB/PB 分链独立展示。
    数据源 → 归类: 上游账本(chemicalbook_seed) / 队列(cas_jobs·pubchem_jobs)
    / 落库(chemical_cb·chemical_pubchem·supplier_*) / 负面账本(cb_negative_observations)
    / 闸门(redis) / 运行时(worker_clients)。
    字段语义: queue=queued·leased·error 三态; rows={today,total} 两链同义;
    rate_1h=近一小时真实落库行数; error_buckets 只统计 status='error' 的留痕分桶。"""
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

    # ── 队列三态 + error 分桶 (小表, 快, 不走缓存) ──
    cb_queue = await chain_counts("cas_jobs")
    cb_errors = await error_buckets("cas_jobs")
    pb_queue = await chain_counts("pubchem_jobs")
    pb_errors = await error_buckets("pubchem_jobs")

    # ── 数据口径 (0910 管理场景重构): 总量+今日新增成对; 无 not_found 维度
    # (negative 走 observations 账本, chemical_cb 只存 positive, 展示死维度已删)。
    # 性能: 每表一次聚合扫描, 串行 (AsyncSession 不允许并发 execute)。
    # 这些"总量"精确统计必须全表扫 (120万/290万行, 合计 ~3s), 管理员视角
    # 几十秒的新鲜度足够 → 60s 进程内 TTL 缓存。队列/闸门/最新条不走缓存。
    #
    # A1 (0912) 分区容错: 大表统计拆 critical / optional 两类 —
    #   critical  cb_locales + pb (管道核心落库口径, 失败=整页不可信 → 抛出)
    #   optional  supplier / seed / negative (诊断性, 失败=available=false 降级)
    # 每个 section 独立 try/except: 单块失败 log section+exception, 绝不 0 冒充。
    # 缓存治理: last-known-good + 单飞(asyncio.Lock) + stale 标记, 见模块头注释。

    def _fresh_optional(section: str, value, snapshot: dict) -> dict:
        # 成功: available=true + 值
        return {"available": True, "error": None, "value": value}

    async def _refresh_stats(db) -> dict:
        """全量重扫描(critical 串行 + optional 各自容错), 返回 snapshot dict。
        critical 失败向上抛(调用方决定降级路径); optional 失败埋 available=False。"""
        snapshot: dict[str, Any] = {}
        cb_locales, pb_today, pb_last_1h, pb_total_rows = await _scan_critical(db)
        snapshot["critical"] = (cb_locales, pb_today, pb_last_1h, pb_total_rows)
        snapshot["optional"] = {}
        for section, fn in (("supplier", _scan_supplier),
                            ("seed", _scan_seed),
                            ("negative", _scan_negative)):
            try:
                snapshot["optional"][section] = _fresh_optional(
                    section, await fn(db), snapshot)
            except Exception as exc:  # noqa: BLE001 — 逐块降级, 必须吞
                logger.exception("pipeline stats section=%s failed", section)
                snapshot["optional"][section] = {
                    "available": False,
                    "error": str(exc)[:200],
                    "value": None,
                }
        snapshot["generated_at"] = (await db.execute(text("SELECT now()"))).scalar().isoformat()
        return snapshot

    cached = _PIPELINE_STATS_CACHE.get("v")
    stats_stale = False
    if cached is None or _time.monotonic() - cached["ts"] > _PIPELINE_STATS_TTL:
        if _PIPELINE_STATS_LOCK.locked() and cached is not None:
            # 有旧缓存 + 别人在刷新: 立即返回旧 snapshot 标 stale —— 不排队不重扫
            stats_stale = True
        else:
            # 无缓存(冷启动)或锁空闲: 走锁。冷启动时若别人正在首次刷新,
            # 本请求在锁上等待(single-flight), 其完成后读取其结果 —— 不会
            # 带着 cached=None 走下去, 也不会各自重扫。
            async with _PIPELINE_STATS_LOCK:
                # 双查: 排队期间别人已刷新完就不再扫
                cached2 = _PIPELINE_STATS_CACHE.get("v")
                if cached2 is not None and _time.monotonic() - cached2["ts"] <= _PIPELINE_STATS_TTL:
                    cached = cached2
                else:
                    try:
                        fresh = await _refresh_stats(db)
                        _PIPELINE_STATS_CACHE["v"] = {
                            "v": fresh, "ts": _time.monotonic(),
                        }
                        cached = _PIPELINE_STATS_CACHE["v"]
                    except Exception:
                        logger.exception("pipeline stats critical refresh failed")
                        if _PIPELINE_STATS_CACHE.get("v") is None:
                            raise   # 从无成功 snapshot: 明确失败, 不造 0
                        cached = _PIPELINE_STATS_CACHE["v"]
                        stats_stale = True  # last-known-good: 旧 snapshot 继续, 标 stale
    stats = cached["v"]
    stats_generated_at = stats.get("generated_at") or cached.get("wall") or now_iso
    stats_age_s = int(_time.monotonic() - cached["ts"])
    (cb_locales, pb_today, pb_last_1h, pb_total_rows) = stats["critical"]
    opt = stats["optional"]
    # optional sections: available=True 时解包为直接值 + available 元数据;
    # available=False 时 value=None —— 前端按"暂不可用"渲染, 绝不冒充 0。
    supplier_wrap = opt["supplier"]
    supplier = supplier_wrap["value"] if supplier_wrap["available"] else None
    seed_wrap = opt["seed"]
    seed_stats = seed_wrap["value"] if seed_wrap["available"] else None
    neg_wrap = opt["negative"]
    neg_stats = neg_wrap["value"] if neg_wrap["available"] else None
    optional_meta = {k: {"available": v["available"],
                         "error": v.get("error")} for k, v in opt.items()}

    # 落库口径: rows.today / rows.total 两链同语义 (total=落库总量, 非"今日")
    cb_today = sum(x["today"] for x in cb_locales)
    cb_total = sum(x["total"] for x in cb_locales)
    cb_rate = sum(x["last_1h"] for x in cb_locales)

    # ── 闸门(redis db1, 0902 口径) —— optional: 失败→available=False, 不炸页 ──
    gates: dict = {}
    gates_available = True
    gates_error: str | None = None
    try:
        from .core.cache import get_cache
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
    except Exception as exc:  # noqa: BLE001 — optional 降级
        logger.exception("pipeline gates section failed")
        gates_available = False
        gates_error = str(exc)[:200]
        # 降级不空壳: 前端 data.gates.<chain> 必须可解析(值语义靠 gates_meta.available)
        for ch in ("pubchem", "cb"):
            gates.setdefault(ch, {"streak": 0, "silent": False, "silent_remaining_s": 0})

    # ── worker 在线状态 (A1: enabled ≠ online, runtime projection 见 pipeline_health) ──
    from .services.pipeline_health import (
        build_worker_runtimes, chain_health as chain_health_model,
        RECENT_SUCCESS_S,
    )
    worker_rows = (await db.execute(text("""
        SELECT worker_id, display_name, enabled, scopes, last_seen_at
        FROM maintenance.worker_clients ORDER BY worker_id
    """))).fetchall()
    now_dt = (await db.execute(text("SELECT now()"))).scalar()
    runtimes = build_worker_runtimes(worker_rows, now_dt)

    # ── 各链最新 10 条 (NULLS LAST: fetched_at 为空的旧行不得占据榜首) ──
    # 行形状统一 {chain, chemical_id, source, ref, title, at} —— 只暴露界面真正要用的字段。
    latest_cb = [
        {"chain": "CB", "chemical_id": int(r[0]),
         "source": r[1] or "zh-CN", "ref": r[2] or "—",
         "title": r[4] or "—",
         "at": r[3].isoformat() if r[3] else None}
        for r in (await db.execute(text("""
            SELECT cc.chemical_id, cc.locale, cc.cb_number, cc.fetched_at, c.preferred_name
            FROM chemistry.chemical_cb cc
            LEFT JOIN chemistry.chemicals c ON c.id = cc.chemical_id
            ORDER BY cc.fetched_at DESC NULLS LAST LIMIT 10
        """))).fetchall()
    ]
    latest_pb = [
        {"chain": "PB", "chemical_id": int(r[0]),
         "source": "PUG View", "ref": str(r[2]) if r[2] else "—",
         "title": r[1] or r[3] or "—",
         "at": r[4].isoformat() if r[4] else None}
        for r in (await db.execute(text("""
            SELECT p.chemical_id, p.record_title, c.pubchem_cid, c.preferred_name, p.fetched_at
            FROM chemistry.chemical_pubchem p
            LEFT JOIN chemistry.chemicals c ON c.id = p.chemical_id
            ORDER BY p.fetched_at DESC NULLS LAST LIMIT 10
        """))).fetchall()
    ]
    cb_latest_at = latest_cb[0]["at"] if latest_cb else None
    pb_latest_at = latest_pb[0]["at"] if latest_pb else None

    # ── 队列老化(critical: 小表快查) —— 健康判定的真实依据 ──
    # 注: extract(...) FILTER 不是合法语法, 用子查询聚合(小表, 无代价)。
    async def queue_aging(table: str) -> dict:
        row = (await db.execute(text(f"""
            SELECT
              (SELECT extract(epoch from now() - min(created_at))
                 FROM maintenance.{table} WHERE status='queued'),
              (SELECT extract(epoch from now() - min(lease_expires_at))
                 FROM maintenance.{table} WHERE status='leased'),
              (SELECT min(lease_expires_at)
                 FROM maintenance.{table} WHERE status='leased')
        """))).fetchone()
        return {
            "oldest_queued_age_s": int(row[0]) if row[0] is not None else None,
            "oldest_leased_age_s": int(row[1]) if row[1] is not None else None,
            "oldest_lease_expires_at": row[2].isoformat() if row[2] else None,
        }

    cb_aging = await queue_aging("cas_jobs")
    pb_aging = await queue_aging("pubchem_jobs")

    def _parse(iso: str | None):
        return datetime.fromisoformat(iso) if iso else None

    # ── 单链健康(A1 语义: healthy/idle/backlogged/stalled/degraded/unavailable) ──
    cb_health = chain_health_model(
        scope="cas", queued=cb_queue["queued"], leased=cb_queue["leased"],
        error=cb_queue["error"], latest_success_at=_parse(cb_latest_at),
        gate_silent=bool(gates_available and gates.get("cb") and gates["cb"]["silent"]),
        metrics_available=True, worker_runtimes=runtimes, now=now_dt)
    pb_health = chain_health_model(
        scope="pubchem", queued=pb_queue["queued"], leased=pb_queue["leased"],
        error=pb_queue["error"], latest_success_at=_parse(pb_latest_at),
        gate_silent=bool(gates_available and gates.get("pubchem") and gates["pubchem"]["silent"]),
        metrics_available=True, worker_runtimes=runtimes, now=now_dt)
    # gates 不可用本身是 degraded 信号(不足以 unavailable)
    if not gates_available:
        for h in (cb_health, pb_health):
            if h["status"] in ("healthy", "idle"):
                h["status"] = "degraded"
                h["reasons"].append("闸门指标不可用")

    # optional sections 统一形状: {available, error, value} —— 前端只认这个
    def _wrap(meta: dict, value) -> dict:
        return {"available": meta["available"], "error": meta.get("error"), "value": value}

    return {
        # supplier/seed/negative = CB secondary diagnostics(降级区), 不与 queue health 抢一级
        "supplier": _wrap(optional_meta["supplier"], supplier),
        "cb": {
            "queue": cb_queue, "error_buckets": cb_errors,
            "rate_1h": cb_rate,
            "latest_at": cb_latest_at,
            "aging": cb_aging,
            "health": cb_health,
            "rows": {"today": int(cb_today), "total": int(cb_total)},
            "locales": cb_locales,       # 五语种: 每个 {locale, today, total, last_1h}
            "seed": _wrap(optional_meta["seed"], seed_stats),        # 上游账本
            "negative": _wrap(optional_meta["negative"], neg_stats), # 负面观测
        },
        "pb": {
            "queue": pb_queue, "error_buckets": pb_errors,
            "rate_1h": int(pb_last_1h),
            "latest_at": pb_latest_at,
            "aging": pb_aging,
            "health": pb_health,
            "rows": {"today": int(pb_today), "total": int(pb_total_rows)},
        },
        "gates": gates,
        "gates_meta": {"available": gates_available, "error": gates_error},
        "workers": [
            {"worker_id": w.worker_id, "display_name": w.display_name,
             "enabled": w.enabled, "scopes": w.scopes,
             "runtime": w.runtime,                    # online/stale/offline/disabled
             "last_seen_at": w.last_seen_at.isoformat() if w.last_seen_at else None,
             "last_seen_age_s": int(w.last_seen_age_s) if w.last_seen_age_s is not None else None}
            for w in runtimes
        ],
        "latest": {"cb": latest_cb, "pb": latest_pb},
        # 统计快照元数据: 前端如实显示统计时间, stale 不伪装实时
        "stats": {
            "generated_at": stats_generated_at,
            "stale": stats_stale,
            "age_seconds": stats_age_s,
            "ttl_seconds": int(_PIPELINE_STATS_TTL),
            "sections": optional_meta,
        },
        "generated_at": now_iso,
    }


@router.post("/pipeline/{chain}/errors/revive")
async def revive_errors(
    chain: str,
    actor: Actor = Depends(admin),
    db=Depends(get_db),
):
    """error 行手动复活(0902, 0911 复核): 一键把该链全部 error 态翻回 queued。
    与 worker 的"过期租约回收"同口径 —— error 行在入 error 态时已清空租约字段,
    故翻态只需改 status/updated_at; last_error_code 保留为留痕(下次派发失败会覆盖)。
    claim 只认 status='queued', 翻态后即可被 worker 正常认领。"""
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

