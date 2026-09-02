"""Authenticated POST-only maintenance API used by the PubChem worker."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text

from .core.cache import cache_delete, get_cache
from .core.config import settings
from .core.database import get_db
from .schemas.workapi import LeaseBody, LeaseProof, CompleteBody, ErrorBody, CasLeaseBody, CasCompleteBody
from .services.workqueue import (
    lease_hash, verified_lease, as_json_object, sync_chemical_core,
    upsert_details, verified_cas_lease,
)
from .services.gate import (
    gate_silence_remaining, gate_record_error, gate_record_success,
    gate_unlock_error_rows,
)

router = APIRouter(prefix="/workapi/v1", tags=["workapi"])

NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True)
class WorkerContext:
    worker_id: str
    max_lease_jobs: int


async def authenticated_worker(
    request: Request,
    db=Depends(get_db),
    authorization: str | None = Header(default=None),
    x_worker_id: str | None = Header(default=None),
    x_work_timestamp: str | None = Header(default=None),
    x_work_nonce: str | None = Header(default=None),
    x_work_signature: str | None = Header(default=None),
) -> WorkerContext:
    body = await request.body()
    if len(body) > settings.worker_max_body_bytes:
        raise HTTPException(413, "worker payload too large")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing worker token")
    token = authorization[7:].strip()
    if len(token) < 32 or not x_worker_id:
        raise HTTPException(401, "invalid worker identity")
    try:
        timestamp = int(x_work_timestamp or "")
    except ValueError as exc:
        raise HTTPException(401, "invalid worker timestamp") from exc
    if abs(int(time.time()) - timestamp) > settings.worker_signature_skew_seconds:
        raise HTTPException(401, "expired worker signature")
    if not x_work_nonce or not NONCE_RE.fullmatch(x_work_nonce):
        raise HTTPException(401, "invalid worker nonce")

    body_hash = hashlib.sha256(body).hexdigest()
    signed = "\n".join(
        (str(timestamp), x_work_nonce, request.method.upper(), request.url.path, body_hash)
    ).encode()
    expected = hmac.new(token.encode(), signed, hashlib.sha256).hexdigest()
    if not x_work_signature or not hmac.compare_digest(expected, x_work_signature.lower()):
        raise HTTPException(401, "invalid worker signature")

    token_hash = hashlib.sha256(token.encode()).digest()
    scope_needed = "cas" if request.url.path.startswith("/workapi/v1/cas/") else "pubchem"
    row = (await db.execute(text("""
        SELECT worker_id,max_lease_jobs
        FROM maintenance.worker_clients
        WHERE worker_id=:worker_id AND token_hash=:token_hash
          AND enabled AND disabled_at IS NULL AND :scope=ANY(scopes)
    """), {"worker_id": x_worker_id, "token_hash": token_hash, "scope": scope_needed})).fetchone()
    if not row:
        raise HTTPException(401, "unknown or disabled worker")

    redis = await get_cache()
    nonce_key = f"workapi:nonce:{x_worker_id}:{x_work_nonce}"
    try:
        accepted = await redis.set(nonce_key, "1", ex=600, nx=True)
    except Exception as exc:
        raise HTTPException(503, "worker replay protection unavailable") from exc
    if not accepted:
        raise HTTPException(409, "replayed worker request")
    # The worker calls this API throughout a task. Throttle last-seen
    # persistence so heartbeats do not create avoidable WAL churn.
    seen_key = f"workapi:last-seen:{x_worker_id}"
    if await redis.set(seen_key, "1", ex=300, nx=True):
        await db.execute(text("""
            UPDATE maintenance.worker_clients
            SET last_seen_at=now() WHERE worker_id=:worker_id
        """), {"worker_id": x_worker_id})
    return WorkerContext(str(row[0]), int(row[1]))



@router.post("/jobs/lease")
async def lease_jobs(
    body: LeaseBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    limit = min(body.max_jobs, worker.max_lease_jobs)
    if "pubchem" not in body.capabilities:
        await db.commit()
        return {"jobs": [], "retry_after_seconds": 30}
    try:
        redis = await get_cache()
        # ── 闸门(§4): 通道静默期不派发, job 留表, worker 零空转 ──
        # 阶梯状态在 redis(通道计数+静默截止), 与 lease 同进程语义;
        # redis 缺席=无闸门(保守放行), 计数由 /jobs/error 与 /jobs/complete 维护。
        gate_wait = await gate_silence_remaining(redis, "pubchem")
        if gate_wait > 0:
            await db.commit()
            return {"jobs": [], "retry_after_seconds": max(5, int(gate_wait) + 1)}
        # 过期租约回收: 本地问题非通道问题 — 直接回队, 不进计数。
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET status='queued',lease_owner=NULL,lease_token_hash=NULL,
                lease_expires_at=NULL,updated_at=now(),
                last_error_code='lease_expired'
            WHERE status='leased' AND lease_expires_at<=now()
        """))
        # claim 只认 queued — error 行=留痕占位, 永不派发(0901 裁定);
        # 复活走同请求到达入列口 UPDATE 翻态。
        rows = (await db.execute(text("""
            SELECT j.id,j.chemical_id,j.query_value
            FROM maintenance.pubchem_jobs j
            WHERE j.status='queued'
            ORDER BY j.priority DESC,j.id
            LIMIT :limit FOR UPDATE OF j SKIP LOCKED
        """), {"limit": limit})).fetchall()
        leased = []
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text("""
                UPDATE maintenance.pubchem_jobs
                SET status='leased',lease_owner=:worker_id,lease_token_hash=:token_hash,
                    lease_expires_at=now()+make_interval(secs=>:lease_seconds),
                    updated_at=now()
                WHERE id=:job_id
            """), {
                "worker_id": worker.worker_id,
                "token_hash": lease_hash(token),
                "lease_seconds": settings.worker_job_lease_seconds,
                "job_id": row[0],
            })
            leased.append({
                "job_id": row[0],
                "lease_token": token,
                "chemical_id": row[1],
                "cid": int(row[2]),
                "lease_seconds": settings.worker_job_lease_seconds,
            })
        await db.commit()
        return {"jobs": leased, "retry_after_seconds": 2 if leased else 5}
    except Exception:
        await db.rollback()
        raise



@router.post("/jobs/complete")
async def complete_job(
    body: CompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """整包入库(0901 定案): 拉到就 update, 全字段覆盖, 无校验。
    result 空 → job 出表, 数据层零动作。"""
    try:
        job = await verified_lease(db, body, worker.worker_id)
        result = body.result
        chemical_id = job[1]
        payload = as_json_object(result.get("payload")) if isinstance(result, dict) else {}
        if payload:
            await upsert_details(db, int(chemical_id), payload)
            core = payload.get("core") or {}
            await sync_chemical_core(
                db, int(chemical_id), core,
                record_title=payload.get("record_title"),
                synonyms=payload.get("synonyms") or None,
                cas_numbers=payload.get("cas_numbers") or None,
                main_table_ids=payload.get("main_table_ids") or None,
            )
        # 出表: complete 即 DELETE, job 是纯队列不承载历史。
        await db.execute(text("""
            DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id
        """), {"job_id": body.job_id})
        await db.commit()
        # 闸门归零: 一次成功 = 通道连击清零 + error 行复活回队。
        redis = await get_cache()
        await gate_record_success(redis, "pubchem")
        await gate_unlock_error_rows(db, "pubchem")
        await db.commit()
        if chemical_id is not None:
            await cache_delete(f"v1:chemical:{chemical_id}")
        return {"status": "ok", "chemical_id": chemical_id, "empty": not payload}
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/jobs/error")
async def error_job(
    body: ErrorBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """worker error(0901 终版): 行留 error 态占位(有人要过、没拿到),
    连击+1(网络类)。无时间调度字段 — 复活=同请求到达入列口 UPDATE 翻态。"""
    try:
        await verified_lease(db, body, worker.worker_id)
        redis = await get_cache()
        streak = 0
        # pubchem_empty = 网络通但内容空: 留痕但不计连击(非通道劣化信号)。
        if body.error_code != "pubchem_empty":
            streak = await gate_record_error(redis, "pubchem")
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET status='error',
                last_error_code=:code,last_error_detail=:detail,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                updated_at=now()
            WHERE id=:job_id
        """), {
            "code": body.error_code, "detail": body.error_detail, "job_id": body.job_id,
        })
        await db.commit()
        return {"status": "error", "streak": streak}
    except Exception:
        await db.rollback()
        raise


# ---------------------------------------------------------------- cas jobs
# 与 pubchem jobs 同协议(HMAC/租约/心跳/nonce), 独立表 maintenance.cas_jobs。
# worker 认领时声明 capabilities=["cas"]; scopes 检查在 authenticated_worker。


@router.post("/cas/jobs/lease")
async def cas_lease_jobs(
    body: CasLeaseBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    limit = min(body.max_jobs, worker.max_lease_jobs)
    if "cas" not in body.capabilities:
        await db.commit()
        return {"jobs": [], "retry_after_seconds": 30}
    try:
        # 到期自扫(替代 SSR 触发, CF 缓存场景同样生效) + 过期租约回收
        from .services.cb import scan_expired_into_queue
        redis = await get_cache()
        # ── 闸门(§4): cb 通道静默期不派发 ──
        gate_wait = await gate_silence_remaining(redis, "cb")
        if gate_wait > 0:
            await db.commit()
            return {"jobs": [], "retry_after_seconds": max(5, int(gate_wait) + 1)}
        await scan_expired_into_queue(db)
        # 过期租约回收(§4): 本地问题非通道问题 — 直接回队, 不进计数。
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET status='queued',lease_owner=NULL,lease_token_hash=NULL,
                lease_expires_at=NULL,updated_at=now(),
                last_error_code='lease_expired'
            WHERE status='leased' AND lease_expires_at<=now()
        """))
        # FOR UPDATE 不能落 LEFT JOIN 的 nullable 侧: 先锁 cas_jobs,
        # cb_number(语言行寻址键)另查补齐。
        # 0902 剥离: 负缓存终态拦截 CTE 整段删除 — not 行已清零且不再写入,
        # 拦截永不命中; 且此段曾静默删除 34k 修复任务(lease拦截血案)。
        claim = (await db.execute(text("""
            WITH candidates AS (
                SELECT j.id, j.chemical_id, j.cas_number,
                       coalesce(j.request_context->>'locale','zh-CN') AS locale
                FROM maintenance.cas_jobs j
                WHERE j.status='queued'
                ORDER BY j.priority DESC, j.id
                LIMIT :limit
                FOR UPDATE OF j SKIP LOCKED
            )
            SELECT c.id, c.chemical_id, c.cas_number,
                   c.locale
            FROM candidates c
        """), {
            "limit": limit,
        })).fetchall()
        rows = [(r[0], r[1], r[2], r[3]) for r in claim]
        cb_map: dict[int, str | None] = {}
        if rows:
            cb_rows = (await db.execute(text("""
                SELECT id, cb_number FROM chemistry.chemicals
                WHERE id = ANY(CAST(:ids AS integer[]))
            """), {"ids": [r[1] for r in rows if r[1] is not None]})).fetchall()
            cb_map = {r[0]: r[1] for r in cb_rows}
        leased = []
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text("""
                UPDATE maintenance.cas_jobs
                SET status='leased',lease_owner=:worker_id,lease_token_hash=:token_hash,
                    lease_expires_at=now()+make_interval(secs=>:lease_seconds),
                    updated_at=now()
                WHERE id=:job_id
            """), {
                "worker_id": worker.worker_id,
                "token_hash": lease_hash(token),
                "lease_seconds": settings.worker_job_lease_seconds,
                "job_id": row[0],
            })
            leased.append({
                "job_id": row[0],
                "lease_token": token,
                "chemical_id": row[1],
                "cas_number": row[2],
                "lease_seconds": settings.worker_job_lease_seconds,
                "locale": row[3] or "zh-CN",
                "cb_number": cb_map.get(row[1]),
            })
        await db.commit()
        return {"jobs": leased, "retry_after_seconds": 2 if leased else 10}
    except Exception:
        await db.rollback()
        raise


@router.post("/cas/jobs/heartbeat")
async def cas_heartbeat(
    body: LeaseProof,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        await verified_cas_lease(db, body, worker.worker_id, lock=False)
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET lease_expires_at=now()+make_interval(secs=>:seconds),
                updated_at=now() WHERE id=:job_id
        """), {"seconds": settings.worker_job_lease_seconds, "job_id": body.job_id})
        await db.commit()
        return {"status": "leased", "lease_seconds": settings.worker_job_lease_seconds}
    except Exception:
        await db.rollback()
        raise


@router.post("/cas/jobs/complete")
async def cas_complete_job(
    body: CasCompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    from .services.cb import CACHE_KEY, apply_structure_fill, resolve_structure, upsert_externals
    try:
        job = await verified_cas_lease(db, body, worker.worker_id)
        chemical_id = job[1]
        cas_number = job[2]
        # 占位行机制(2026-08-29定): 搜索miss入队时已占主表行, 任务必有
        # chemical_id。无主行建行分支已删除 — complete 落 cb 表数据 +
        # 结构三件回填(占位行靠这个出图)。
        if chemical_id is None:
            # 兼容残量: 老无主行任务(存量10条跑完即绝迹) — 出表。
            payload = body.result
            await db.execute(text("""
                DELETE FROM maintenance.cas_jobs WHERE id=:job_id
            """), {"job_id": body.job_id})
            await db.commit()
            return {"status": payload.status, "standalone": True}
        payload = body.result
        status = payload.status
        entry = payload.entry if status == "ok" else None
        locale = payload.locale
        suppliers = payload.suppliers if status == "ok" and locale == "zh-CN" else []
        if status == "ok":
            # 结构三件只补空: 占位行/无结构行靠 CB mol 回填出图;
            # cid 在的行 PubChem 早填过(coalesce no-op)。
            await apply_structure_fill(
                db, chemical_id, resolve_structure(entry, payload.mol)
            )
        try:
            await upsert_externals(
                db, chemical_id=chemical_id, cas_number=cas_number,
                entry=entry, suppliers=suppliers, status=status,
                cb_number=payload.cb_number, locale=locale,
            )
        except ValueError as exc:
            # 载荷异常: 不打死 — 留 error 行占位(0901 终版: 无时间字段, 复活=同请求翻态)。
            await db.execute(text("""
                UPDATE maintenance.cas_jobs
                SET status='error',last_error_code='payload_invalid',
                    last_error_detail=:detail,
                    lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                    updated_at=now()
                WHERE id=:job_id
            """), {"job_id": body.job_id, "detail": str(exc)[:2000]})
            await db.commit()
            raise HTTPException(422, str(exc)) from exc
        summary = {
            "chemical_id": chemical_id,
            "status": status,
            "supplier_count": len(suppliers),
            "entry_keys": sorted(entry.keys()) if entry else [],
        }
        # 多语言派发(2026-08-30 准线§2): zh-CN ok 且拿到 cb_number 时, 对
        # 五语言逐一六态判定, 满足才入列(事件驱动, 替代已拆除的 TTL定时扫描)。
        # 语言页靠 cb_number 寻址; 语言任务 complete 不再派生(单点派发)。
        # dedupe :locale 后缀独立去重; 终态拦截在 lease 端已有时限窗。
        if status == "ok" and locale == "zh-CN" and payload.cb_number:
            from .services.cb import cb_decide, enqueue_cas_job
            for lang in ("en", "ja", "de", "ko"):
                decision = await cb_decide(
                    db, chemical_id, lang, has_cb_number=True,
                )
                if decision.startswith("enqueue"):
                    await enqueue_cas_job(
                        db, chemical_id=chemical_id, cas_number=cas_number,
                        priority=30, locale=lang,
                    )
        # 出表(§3): complete 即 DELETE; 闸门归零(§4) cb 通道。
        await db.execute(text("""
            DELETE FROM maintenance.cas_jobs WHERE id=:job_id
        """), {"job_id": body.job_id})
        await db.commit()
        redis = await get_cache()
        await gate_record_success(redis, "cb")
        await gate_unlock_error_rows(db, "cb")
        await db.commit()
        await cache_delete(CACHE_KEY.format(chemical_id=chemical_id))
        return summary
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/cas/jobs/error")
async def cas_error_job(
    body: ErrorBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """worker error(0901 终版): 行留 error 态占位, 连击+1。
    无时间调度字段 — 复活=同请求到达入列口 UPDATE 翻态。"""
    try:
        await verified_cas_lease(db, body, worker.worker_id)
        redis = await get_cache()
        streak = await gate_record_error(redis, "cb")
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET status='error',
                last_error_code=:code,last_error_detail=:detail,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                updated_at=now()
            WHERE id=:job_id
        """), {
            "code": body.error_code, "detail": body.error_detail, "job_id": body.job_id,
        })
        await db.commit()
        return {"status": "error", "streak": streak}
    except Exception:
        await db.rollback()
        raise
