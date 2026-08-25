"""cas-externals: ChemicalBook 中文条目/供应商 懒加载读写层.

机制镜像 enrichment.py(pubchem 链):
- ensure_externals(): fresh 直出 | miss 同步拉(3s 预算,线程池) | stale 出旧+入队
- not_found 落行为负缓存
- 入队 ON CONFLICT 活跃窗口去重
本模块不挂公开路由(批次3 由 /chemicals/{id}/externals 与 SSR 调用);
workapi 的 cas complete 载荷写入也复用此处的 upsert。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from .cache import cache_delete, get_cache
from .database import get_db

# entry 30d / suppliers 7d: 两周期独立驱动 — cas_externals.expires_at 取
# entry 周期(30d), cas_suppliers 自带 fetched_at, 刷新任务同趟刷新两者,
# 任务到期判定 = min(entry 剩余, suppliers 剩余) — 由 ensure 层计算,表结构不感知。
ENTRY_TTL_DAYS = 30
SUPPLIERS_TTL_DAYS = 7
NOT_FOUND_TTL_DAYS = 1  # 负缓存: not_found 行 1 天内不重试
SYNC_FETCH_BUDGET_S = 3.0
CACHE_KEY = "v2:cas-ext:{chemical_id}"
CACHE_TTL_S = 6 * 3600
MAX_ENTRY_JSON_BYTES = 2_000_000  # 双保险: workapi 载荷上限内的条目尺寸


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry_expires() -> datetime:
    return _now() + timedelta(days=ENTRY_TTL_DAYS)


def _not_found_expires() -> datetime:
    return _now() + timedelta(days=NOT_FOUND_TTL_DAYS)


def suppliers_fresh(fetched_at: Any) -> bool:
    if not isinstance(fetched_at, datetime):
        return False
    value = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    return value >= _now() - timedelta(days=SUPPLIERS_TTL_DAYS)


async def get_externals_row(db: Any, chemical_id: int) -> dict[str, Any] | None:
    row = (await db.execute(text("""
        SELECT chemical_id,cas_number,entry_cn,last_status,fetched_at,expires_at
        FROM chemistry.cas_externals WHERE chemical_id=:chemical_id
    """), {"chemical_id": chemical_id})).mappings().fetchone()
    return dict(row) if row else None


async def get_suppliers(db: Any, chemical_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT ref,name,phone,email,website,purity,pack_price,remark
        FROM chemistry.cas_suppliers WHERE chemical_id=:chemical_id ORDER BY ref
    """), {"chemical_id": chemical_id})).fetchall()
    return [dict(r._mapping) for r in rows]


async def upsert_externals(
    db: Any,
    *,
    chemical_id: int,
    cas_number: str,
    entry: dict[str, Any] | None,
    suppliers: list[dict[str, Any]],
    status: str,
) -> None:
    """worker complete 与同步拉取共用的唯一写入口(事务由调用方管理)。"""
    entry_json = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) if entry else None
    if entry_json and len(entry_json.encode()) > MAX_ENTRY_JSON_BYTES:
        raise ValueError("cas entry payload exceeds safety limit")
    expires = _entry_expires() if status == "ok" else (
        _not_found_expires() if status == "not_found" else None
    )
    await db.execute(text("""
        INSERT INTO chemistry.cas_externals
            (chemical_id,cas_number,entry_cn,last_status,fetched_at,expires_at)
        VALUES
            (:chemical_id,:cas_number,CAST(:entry AS jsonb),:status,now(),:expires)
        ON CONFLICT (chemical_id) DO UPDATE SET
            cas_number=excluded.cas_number,
            entry_cn=excluded.entry_cn,
            last_status=excluded.last_status,
            fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at,
            updated_at=now()
    """), {
        "chemical_id": chemical_id, "cas_number": cas_number,
        "entry": entry_json, "status": status, "expires": expires,
    })
    # 供应商: 整组替换(仅 ok 且带列表时; not_found 清空)
    if status == "ok":
        await db.execute(text("""
            DELETE FROM chemistry.cas_suppliers WHERE chemical_id=:chemical_id
        """), {"chemical_id": chemical_id})
        if suppliers:
            await db.execute(text("""
                INSERT INTO chemistry.cas_suppliers
                    (chemical_id,ref,name,phone,email,website,purity,pack_price,remark)
                SELECT :chemical_id,* FROM unnest(
                    CAST(:refs AS text[]),CAST(:names AS text[]),
                    CAST(:phones AS text[]),CAST(:emails AS text[]),CAST(:websites AS text[]),
                    CAST(:purities AS text[]),CAST(:packs AS text[]),CAST(:remarks AS text[]))
                AS t(ref,name,phone,email,website,purity,pack_price,remark)
            """), _suppliers_params(chemical_id, suppliers))
    else:
        await db.execute(text("""
            DELETE FROM chemistry.cas_suppliers WHERE chemical_id=:chemical_id
        """), {"chemical_id": chemical_id})


def _suppliers_params(chemical_id: int, suppliers: list[dict[str, Any]]) -> dict[str, Any]:
    def col(key: str) -> list[str | None]:
        return [s.get(key) for s in suppliers]
    return {
        "chemical_id": chemical_id,
        "refs": col("ref"), "names": col("name"),
        "phones": col("phone"), "emails": col("email"), "websites": col("website"),
        "purities": col("purity"), "packs": col("pack_price"), "remarks": col("remark"),
    }


def _dedupe_key(chemical_id: int, cas_number: str) -> str:
    digest = hashlib.sha256(cas_number.strip().encode()).hexdigest()[:16]
    return f"cas:{chemical_id}:{digest}"


async def enqueue_cas_job(
    db: Any,
    *,
    chemical_id: int,
    cas_number: str,
    priority: int = 50,
    request_context: dict[str, Any] | None = None,
) -> int | None:
    """活跃窗口去重入队; 已有活跃任务时返回 None。"""
    row = (await db.execute(text("""
        INSERT INTO maintenance.cas_jobs
            (chemical_id,cas_number,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:cas_number,:priority,:dedupe_key,
             CAST(:context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','retry')
        DO UPDATE SET priority=greatest(maintenance.cas_jobs.priority,excluded.priority),
                      updated_at=now()
        RETURNING id
    """), {
        "chemical_id": chemical_id, "cas_number": cas_number.strip(),
        "priority": priority, "dedupe_key": _dedupe_key(chemical_id, cas_number),
        "context": json.dumps(request_context or {}, ensure_ascii=False),
    })).fetchone()
    return int(row[0]) if row else None


async def sync_fetch_and_store(
    db: Any, *, chemical_id: int, cas_number: str
) -> dict[str, Any] | None:
    """同步拉取路径(详情页首访)。3s 预算, 线程池执行防阻塞事件循环。

    返回 ensure 状态字典; 网络失败/超时不落 error 行(留给 worker 重试)。
    """
    from caslib.fetch import fetch_cas
    from caslib.parse import parse_entry, parse_suppliers

    async def _fetch() -> tuple[str, dict | None, list]:
        result = await fetch_cas(cas_number, total_budget_s=SYNC_FETCH_BUDGET_S)
        if result.status == "error":
            return "error", None, []
        if result.status == "not_found":
            return "not_found", None, []
        entry = parse_entry(result.cas_html or "")
        suppliers = parse_suppliers(result.cas_html or "", result.supplier_html)
        if entry is None:
            return "not_found", None, []
        return "ok", entry, suppliers

    try:
        status, entry, suppliers = await asyncio.wait_for(
            _fetch(), timeout=SYNC_FETCH_BUDGET_S + 1.5,
        )
    except (asyncio.TimeoutError, Exception):
        return None  # 网络层失败: 不落行, 走入队
    if status == "error":
        return None
    await upsert_externals(
        db, chemical_id=chemical_id, cas_number=cas_number.strip(),
        entry=entry, suppliers=suppliers, status=status,
    )
    await db.commit()
    await cache_delete(CACHE_KEY.format(chemical_id=chemical_id))
    return {"status": status}


async def ensure_externals(
    db: Any, chemical_id: int, *, cas_number: str
) -> dict[str, Any]:
    """ensure 链入口。返回:
    {state: fresh|stale|queued|absent, entry, suppliers, job_id}
    - fresh: 直接出
    - stale: 出旧数据 + 入队刷新
    - absent: 无数据(首访) — 调用方(sync路径)决定同步拉或入队
    """
    redis = await get_cache()
    cache_key = CACHE_KEY.format(chemical_id=chemical_id)
    try:
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
            # 缓存只信任"行仍在有效期内": 轻量校验行 expires_at,
            # 防止行被刷新/外部置过期后缓存继续兜售旧判定
            if payload.get("state") == "fresh":
                probe = (await db.execute(text(
                    "SELECT expires_at,fetched_at FROM chemistry.cas_externals "
                    "WHERE chemical_id=:i"
                ), {"i": chemical_id})).fetchone()
                row_fresh = bool(
                    probe and probe[0] and probe[0] > _now()
                    and suppliers_fresh(probe[1])
                )
                if row_fresh:
                    return payload
                await redis.delete(cache_key)
    except Exception:
        pass

    row = await get_externals_row(db, chemical_id)
    if row is None:
        return {"state": "absent", "entry": None, "suppliers": [], "job_id": None}
    if row["last_status"] == "not_found":
        if row["expires_at"] and row["expires_at"] > _now():
            return {"state": "fresh", "entry": None, "suppliers": [], "job_id": None,
                    "negative": True}
        # 负缓存过期: 入队重试
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=row["cas_number"],
            request_context={"reason": "negative_expiry"},
        )
        await db.commit()
        return {"state": "fresh", "entry": None, "suppliers": [], "job_id": job_id,
                "negative": True}
    if row["last_status"] == "error":
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=row["cas_number"],
            request_context={"reason": "error_retry"},
        )
        await db.commit()
        return {"state": "queued", "entry": None, "suppliers": [], "job_id": job_id}
    # ok 行: 新鲜度 = entry expires_at(30d) 与 suppliers 组时间(7d)双周期;
    # 供应商整组替换, 组时间=条目行 fetched_at
    suppliers = await get_suppliers(db, chemical_id)
    entry_fresh = bool(row["expires_at"] and row["expires_at"] > _now())
    sup_fresh = suppliers_fresh(row["fetched_at"])
    payload: dict[str, Any]
    if entry_fresh and sup_fresh:
        payload = {"state": "fresh", "entry": row["entry_cn"], "suppliers": suppliers,
                   "job_id": None}
    else:
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=row["cas_number"], priority=60,
            request_context={"reason": "stale_refresh"},
        )
        await db.commit()
        payload = {"state": "stale", "entry": row["entry_cn"], "suppliers": suppliers,
                   "job_id": job_id}
    try:
        if payload["state"] == "fresh":
            await redis.set(cache_key, json.dumps(payload, ensure_ascii=False,
                                                  default=str), ex=CACHE_TTL_S)
    except Exception:
        pass
    return payload


async def scan_expired_into_queue(db: Any, batch: int = 200) -> int:
    """worker 自扫: expires_at 超期(含 not_found 负缓存到期)分批入队。"""
    rows = (await db.execute(text("""
        SELECT chemical_id,cas_number FROM chemistry.cas_externals
        WHERE expires_at IS NOT NULL AND expires_at<now()
        ORDER BY expires_at LIMIT :batch
    """), {"batch": batch})).fetchall()
    enqueued = 0
    for r in rows:
        job_id = await enqueue_cas_job(
            db, chemical_id=r[0], cas_number=r[1], priority=30,
            request_context={"reason": "expiry_scan"},
        )
        if job_id:
            enqueued += 1
    if enqueued:
        await db.commit()
    return enqueued
