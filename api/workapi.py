"""Authenticated POST-only maintenance API used by the PubChem worker."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text

from .core.cache import cache_delete, get_cache
from .core.config import settings
from .core.database import get_db
from .pubchem_core import number_or_none, validate_synonyms
from .schemas.workapi import LeaseBody, LeaseProof, CompleteBody, ErrorBody, CasLeaseBody, CasCompleteBody
from .services.workqueue import (
    lease_hash, verified_lease, as_json_object, sync_chemical_core,
    upsert_details, verified_cas_lease, _cb_requery_days,
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
        # 过期租约回收(§4): 本地问题非通道问题 — 直接回队, 不进计数。
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET status='queued',lease_owner=NULL,lease_token_hash=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,updated_at=now(),
                last_error_code='lease_expired'
            WHERE status='leased' AND lease_expires_at<=now()
        """))
        rows = (await db.execute(text("""
            SELECT j.id,j.chemical_id,j.query_kind,j.query_value,j.sections,
                   j.attempt_count,c.pubchem_cid,c.smiles
            FROM maintenance.pubchem_jobs j
            LEFT JOIN chemistry.chemicals c ON c.id=j.chemical_id
            WHERE j.status IN ('queued','error') AND j.not_before<=now()
            ORDER BY j.priority DESC,j.not_before,j.id
            LIMIT :limit FOR UPDATE OF j SKIP LOCKED
        """), {"limit": limit})).fetchall()
        leased = []
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text("""
                UPDATE maintenance.pubchem_jobs
                SET status='leased',lease_owner=:worker_id,lease_token_hash=:token_hash,
                    lease_expires_at=now()+make_interval(secs=>:lease_seconds),
                    heartbeat_at=now(),attempt_count=attempt_count+1,updated_at=now()
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
                "query_kind": row[2],
                "query_value": row[3],
                "sections": list(row[4] or []),
                "expected_pubchem_cid": row[6],
                "expected_smiles": row[7],
                "lease_seconds": settings.worker_job_lease_seconds,
            })
        await db.commit()
        return {"jobs": leased, "retry_after_seconds": 2 if leased else 5}
    except Exception:
        await db.rollback()
        raise


@router.post("/jobs/heartbeat")
async def heartbeat(
    body: LeaseProof,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        await verified_lease(db, body, worker.worker_id)
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET heartbeat_at=now(),lease_expires_at=now()+make_interval(secs=>:seconds),
                updated_at=now() WHERE id=:job_id
        """), {"seconds": settings.worker_job_lease_seconds, "job_id": body.job_id})
        await db.commit()
        return {"status": "leased", "lease_seconds": settings.worker_job_lease_seconds}
    except Exception:
        await db.rollback()
        raise



@router.post("/jobs/complete")
async def complete_job(
    body: CompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        job = await verified_lease(db, body, worker.worker_id)
        result = body.result
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        properties = as_json_object(result.get("properties"))
        selected_cid = number_or_none(result.get("selected_cid"), int)
        if selected_cid is not None and selected_cid <= 0:
            selected_cid = None
        chemical_id = job[1]
        if selected_cid is None:
            await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
            await db.commit()
            raise HTTPException(422, "worker did not resolve exactly one PubChem CID")

        candidate_cids = {
            number_or_none(item.get("CID"), int)
            for item in candidates
            if isinstance(item, dict)
        }
        candidate_cids.discard(None)
        if selected_cid not in candidate_cids:
            await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
            await db.commit()
            raise HTTPException(422, "selected CID is absent from candidates")
        if job[2] == "cid" and str(selected_cid) != str(job[3]).strip():
            await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
            await db.commit()
            raise HTTPException(422, "selected CID differs from query")

        chemical = None
        if chemical_id is not None:
            chemical = (await db.execute(text("""
                SELECT id,pubchem_cid,smiles,inchikey FROM chemistry.chemicals WHERE id=:id FOR UPDATE
            """), {"id": chemical_id})).fetchone()
            if not chemical:
                await db.execute(text("""
                    DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id
                """), {"job_id": body.job_id})
                await db.commit()
                raise HTTPException(422, "target chemical no longer exists")
        elif selected_cid is not None:
            chemical = (await db.execute(text("""
                SELECT id,pubchem_cid,smiles,inchikey FROM chemistry.chemicals
                WHERE pubchem_cid=:cid ORDER BY id LIMIT 1 FOR UPDATE
            """), {"cid": selected_cid})).fetchone()
            if chemical:
                chemical_id = chemical[0]

        if chemical and selected_cid is not None:
            if chemical[1] is not None and int(chemical[1]) != selected_cid:
                await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
                await db.commit()
                raise HTTPException(422, "result CID differs from stored PubChem CID")
            returned_inchikey = properties.get("InChIKey")
            expected_inchikey = chemical[3]
            if returned_inchikey and expected_inchikey and returned_inchikey != expected_inchikey:
                await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
                await db.commit()
                raise HTTPException(422, "PubChem InChIKey differs from chemicals.inchikey")

        allowed_for_job = set(job[4] or [])
        sections = as_json_object(result.get("sections"))
        sections = {key: value for key, value in sections.items() if key in {
            "computed", "identifiers", "synonyms", "physical", "safety", "toxicity",
            "regulatory", "pharmacology", "uses",
        } and key in allowed_for_job and isinstance(value, dict)}
        synonyms = None
        if "synonyms" in allowed_for_job:
            if "synonyms" not in sections:
                await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
                await db.commit()
                raise HTTPException(422, "worker omitted requested synonyms")
            try:
                synonyms = validate_synonyms(sections["synonyms"].get("values"))
            except ValueError as exc:
                await db.execute(text("DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id"), {"job_id": body.job_id})
                await db.commit()
                raise HTTPException(422, str(exc)) from exc
        if chemical_id is not None and selected_cid is not None:
            await sync_chemical_core(
                db,
                int(chemical_id),
                properties,
                record_title=result.get("record_title"),
                synonyms=synonyms,
            )
            await upsert_details(db, int(chemical_id), properties, sections, result)

        summary = {
            "selected_cid": selected_cid,
            "chemical_id": chemical_id,
            "candidate_count": len(candidates),
            "candidates": candidates[:10],
            "fetched_sections": sorted(sections),
        }
        result_hash = str(result.get("source_hash") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", result_hash, re.I):
            result_hash = hashlib.sha256(
                json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        # 出表(§3): complete 即 DELETE, job 是纯队列缓存不承载历史。
        await db.execute(text("""
            DELETE FROM maintenance.pubchem_jobs WHERE id=:job_id
        """), {"job_id": body.job_id})
        await db.commit()
        # 闸门归零(§4): 一次成功 = 通道连击清零 + 该通道 error 行解锁。
        redis = await get_cache()
        await gate_record_success(redis, "pubchem")
        await gate_unlock_error_rows(db, "pubchem")
        await db.commit()
        if chemical_id is not None:
            await cache_delete(f"v1:chemical:{chemical_id}")
        return summary
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
    """worker error(§3/§4): 不写数据层, job 留 error 行进阶梯。"""
    try:
        await verified_lease(db, body, worker.worker_id)
        redis = await get_cache()
        streak = await gate_record_error(redis, "pubchem")
        silence = await gate_silence_remaining(redis, "pubchem")
        # 未达门槛(连击<5): 60s 短退避 — 防同一 error 行被瞬间重复派发磨穿;
        # 达门槛: 静默窗=阶梯档时间(5/10/30分钟), 期间 lease 不派发。
        delay = int(silence) if silence > 0 else 60
        not_before_sql = "now()+make_interval(secs=>:silence)"
        await db.execute(text(f"""
            UPDATE maintenance.pubchem_jobs
            SET status='error',not_before={not_before_sql},
                last_error_code=:code,last_error_detail=:detail,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now()
            WHERE id=:job_id
        """), {
            "silence": delay,
            "code": body.error_code, "detail": body.error_detail, "job_id": body.job_id,
        })
        await db.commit()
        return {"status": "error", "streak": streak, "silence_seconds": int(silence)}
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
                lease_expires_at=NULL,heartbeat_at=NULL,updated_at=now(),
                last_error_code='lease_expired'
            WHERE status='leased' AND lease_expires_at<=now()
        """))
        # FOR UPDATE 不能落 LEFT JOIN 的 nullable 侧: 先锁 cas_jobs,
        # cb_number(语言行寻址键)另查补齐。
        # 终态拦截(2026-08-29定)单趟: 候选集内 JOIN 目标语言行, 已 not_found
        # 的任务一条 UPDATE 顺手出表(零上游流量消化), 只返回幸存任务
        # 给分发循环 — 查验与不分发是同一个动作。standalone(chemical_id=NULL)
        # JOIN 不命中, 天然不拦。
        claim = (await db.execute(text("""
            WITH candidates AS (
                SELECT j.id, j.chemical_id, j.cas_number,
                       j.attempt_count,
                       coalesce(j.request_context->>'locale','zh-CN') AS locale
                FROM maintenance.cas_jobs j
                WHERE j.status IN ('queued','error') AND j.not_before<=now()
                ORDER BY j.priority DESC, j.not_before, j.id
                LIMIT :limit
                FOR UPDATE OF j SKIP LOCKED
            ), intercepted AS (
                -- 负缓存命中(数据层已有 not_found 且窗内) = 答案已在, 直接出表。
                DELETE FROM maintenance.cas_jobs j
                WHERE j.id IN (
                    SELECT c.id FROM candidates c
                    JOIN chemistry.chemical_cb cb
                      ON cb.chemical_id=c.chemical_id AND cb.locale=c.locale
                     AND cb.last_status='not_found'
                     -- 重问窗内拦截; 超窗 not_found 放行重问(CB 可能新增收录)。
                     AND cb.fetched_at > now()-(:requery_days||' days')::interval
                    WHERE c.chemical_id IS NOT NULL
                )
                RETURNING j.id
            )
            SELECT c.id, c.chemical_id, c.cas_number, c.attempt_count,
                   c.locale
            FROM candidates c
            WHERE c.id NOT IN (SELECT id FROM intercepted)
        """), {
            "limit": limit,
            "requery_days": str(await _cb_requery_days(db)),
        })).fetchall()
        rows = [(r[0], r[1], r[2], r[3], r[4]) for r in claim]
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
                    heartbeat_at=now(),attempt_count=attempt_count+1,updated_at=now()
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
            SET heartbeat_at=now(),lease_expires_at=now()+make_interval(secs=>:seconds),
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
            # 载荷异常: 不打死 — 留 error 行(not_before 短延迟), 通道不计数。
            await db.execute(text("""
                UPDATE maintenance.cas_jobs
                SET status='error',last_error_code='payload_invalid',
                    last_error_detail=:detail,
                    not_before=now()+make_interval(secs=>300),
                    lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                    heartbeat_at=NULL,updated_at=now()
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
            for lang in ("en", "ja", "de", "ko", "ru"):
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
    """worker error(§3/§4): 不写数据层, job 留 error 行进阶梯(cb 通道)。"""
    try:
        await verified_cas_lease(db, body, worker.worker_id)
        redis = await get_cache()
        streak = await gate_record_error(redis, "cb")
        silence = await gate_silence_remaining(redis, "cb")
        delay = int(silence) if silence > 0 else 60
        not_before_sql = "now()+make_interval(secs=>:silence)"
        await db.execute(text(f"""
            UPDATE maintenance.cas_jobs
            SET status='error',not_before={not_before_sql},
                last_error_code=:code,last_error_detail=:detail,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now()
            WHERE id=:job_id
        """), {
            "silence": delay,
            "code": body.error_code, "detail": body.error_detail, "job_id": body.job_id,
        })
        await db.commit()
        return {"status": "error", "streak": streak, "silence_seconds": int(silence)}
    except Exception:
        await db.rollback()
        raise
