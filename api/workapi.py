"""WorkAPI transport/security adapter (POST-only, HMAC-authenticated).

E6 (WorkAPI State Machine Ownership Closure) 后本模块只负责:
- trusted-plane protocol/security: raw body / Bearer token / worker_id header /
  timestamp+skew / nonce 格式 / HMAC 签名 / body hash / route scope /
  worker scopes / replay protection。``authenticated_worker`` 属 adapter/security。
- neutral error → HTTP status + 逐字 detail 的独占映射
  (``_lease_conflict_http`` / ``_payload_invalid_http``)。

job 状态机(lease / expired recovery / heartbeat / complete / error /
completion receipt / 幂等判定 / 事务 / 提交后 housekeeping)归
``api.services.workapi_jobs``; 本模块不再持有业务 SQL 或业务 commit。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text

from .core.cache import get_cache

logger = logging.getLogger(__name__)
from .core.config import settings
from .core.database import get_db
from .schemas.workapi import LeaseBody, LeaseProof, CompleteBody, ErrorBody, CasLeaseBody, CasCompleteBody, IdentityCompleteBody
from .services import workapi_jobs as jobs
from .services.workqueue import LeaseConflictError, PayloadInvalidError

router = APIRouter(prefix="/workapi/v1", tags=["workapi"])

NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _lease_conflict_http(exc: LeaseConflictError) -> HTTPException:
    """E5: service 的 neutral 租约冲突 → 既有 HTTP 409 + 逐字 detail。

    映射归 adapter 独占: service 只表达语义, 不 import transport 框架。
    """
    return HTTPException(409, exc.detail)


def _payload_invalid_http(exc: PayloadInvalidError) -> HTTPException:
    """E6: service 的 neutral payload_invalid → 既有 HTTP 422 + 逐字 detail。

    CAS complete 载荷语义无效(既有 422 路径)的唯一映射点。
    """
    return HTTPException(422, exc.detail)

# ---------------------------------------------------------------------------
# P0 fail-closed scope gate (0912 Worker trusted plane 审计 P0-1):
# identity discovery 按业务定义走 pubchem scope(不新增 identity scope)。
# ---------------------------------------------------------------------------
# P0-1(0912 correction): 精确 (method, exact path) → scope 映射。
# 严禁 prefix/family 继承 — 未逐条列出的 path 一律 None(fail-closed 403)。
ROUTE_SCOPE: dict[tuple[str, str], str] = {
    ("POST", "/workapi/v1/jobs/lease"): "pubchem",
    ("POST", "/workapi/v1/jobs/complete"): "pubchem",
    ("POST", "/workapi/v1/jobs/error"): "pubchem",
    ("POST", "/workapi/v1/cas/jobs/lease"): "cas",
    ("POST", "/workapi/v1/cas/jobs/heartbeat"): "cas",
    ("POST", "/workapi/v1/cas/jobs/complete"): "cas",
    ("POST", "/workapi/v1/cas/jobs/error"): "cas",
    ("POST", "/workapi/v1/identity/jobs/lease"): "pubchem",
    ("POST", "/workapi/v1/identity/jobs/complete"): "pubchem",
    ("POST", "/workapi/v1/identity/jobs/error"): "pubchem",
}


def resolve_route_scope(method: str, path: str) -> str | None:
    """精确 method+path → scope; 无精确匹配 → None(调用方 403 fail-closed)。

    显式枚举全部 10 个 WorkAPI 端点, 不做 prefix/family 推导:
    /workapi/v1/jobs/admin、/cas/jobs/admin、/identity/jobs/admin、
    /workapi/v1/jobs/<未列出子路径>、/workapi/v2/*、GET 已知 path
    全部 → None。新增端点必须同步登记本表, 否则默认拒绝。
    """
    return ROUTE_SCOPE.get((method.upper(), path))


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
    # P0-1: 显式 route-family → scope; 未知 path → 403(fail-closed)
    scope_needed = resolve_route_scope(request.method, request.url.path)
    if scope_needed is None:
        raise HTTPException(403, "workapi route is not mapped to any scope")
    row = (await db.execute(text("""
        SELECT worker_id,max_lease_jobs
        FROM maintenance.worker_clients
        WHERE worker_id=:worker_id AND token_hash=:token_hash
          AND enabled AND disabled_at IS NULL AND :scope=ANY(scopes)
    """), {"worker_id": x_worker_id, "token_hash": token_hash, "scope": scope_needed})).fetchone()
    if not row:
        raise HTTPException(401, "unknown or disabled worker")

    redis = await get_cache()
    # 防重放自洽性: 时间闸(skew±300s)已拦下所有晚期重放, nonce只需覆盖
    # 300s窗; TTL=600s=2×skew是冗余设计。改 skew 时必须保持 TTL ≥ 2×skew。
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
    return await jobs.lease_pubchem_jobs(
        db, worker_id=worker.worker_id, max_lease_jobs=worker.max_lease_jobs,
        max_jobs=body.max_jobs, capabilities=body.capabilities)


@router.post("/jobs/complete")
async def complete_job(
    body: CompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """整包入库(0901 定案): 拉到就 update, 全字段覆盖, 无校验。
    result 空 → job 出表, 数据层零动作。
    P0-2: active lease 缺失时查 completion receipt — 同 worker+同
    lease_token_hash 的重试返回幂等 ack, 不再 409(协议确认幂等)。"""
    try:
        return await jobs.complete_pubchem_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token, result=body.result)
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc


@router.post("/jobs/error")
async def error_job(
    body: ErrorBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """worker error(0901 终版): 行留 error 态占位(有人要过、没拿到),
    连击+1(网络类)。无时间调度字段 — 复活=同请求到达入列口 UPDATE 翻态。"""
    try:
        return await jobs.fail_pubchem_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token, error_code=body.error_code,
            error_detail=body.error_detail)
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc


# ---------------------------------------------------------------- cas jobs
# 与 pubchem jobs 同协议(HMAC/租约/心跳/nonce), 独立表 maintenance.cas_jobs。
# worker 认领时声明 capabilities=["cas"]; scopes 检查在 authenticated_worker。


@router.post("/cas/jobs/lease")
async def cas_lease_jobs(
    body: CasLeaseBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    return await jobs.lease_cas_jobs(
        db, worker_id=worker.worker_id, max_lease_jobs=worker.max_lease_jobs,
        max_jobs=body.max_jobs, capabilities=body.capabilities)


@router.post("/cas/jobs/heartbeat")
async def cas_heartbeat(
    body: LeaseProof,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        return await jobs.heartbeat_cas_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token)
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc


@router.post("/cas/jobs/complete")
async def cas_complete_job(
    body: CasCompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        return await jobs.complete_cas_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token, result=body.result)
    except PayloadInvalidError as exc:
        raise _payload_invalid_http(exc) from exc
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc


@router.post("/cas/jobs/error")
async def cas_error_job(
    body: ErrorBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """worker error(0901 终版): 行留 error 态占位, 连击+1。
    无时间调度字段 — 复活=同请求到达入列口 UPDATE 翻态。"""
    try:
        return await jobs.fail_cas_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token, error_code=body.error_code,
            error_detail=body.error_detail)
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc


@router.post("/identity/jobs/lease")
async def lease_identity_jobs(
    body: LeaseBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """discovery lease。claim 只认 queued; error 行留痕永不派发(对齐纪律)。
    闸门复用 pubchem 命名空间(与 whole_record 同通道连击计数)。"""
    return await jobs.lease_identity_jobs(
        db, worker_id=worker.worker_id, max_lease_jobs=worker.max_lease_jobs,
        max_jobs=body.max_jobs, capabilities=body.capabilities)


@router.post("/identity/jobs/complete")
async def complete_identity_job(
    body: IdentityCompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """discovery complete: 0→not_found / >1→ambiguous / 1→candidate handoff
    (canonicalize → freshness recheck → 原子入 pubchem_jobs → candidate,
    任一步失败整事务 rollback — §3 修正3)。闸门成功归零与 pubchem 同源。
    P0-2: 结果行保留(审计+负缓存), 另记 completion receipt 供重试幂等 ack。"""
    try:
        return await jobs.complete_identity_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token, cid_list=body.cid_list)
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc


# ---------------------------------------------------------------------------
# P1-5 retention: completion receipt 简单时间保留。
# 保留窗 = 30 天(协议重试窗口 nonce TTL 600s × 安全余量 + 故障调查窗口)。
# 删除语句常驻于此, 巡检/维护时手动执行; 不建 daemon/service/cron。
#   DELETE FROM maintenance.workapi_completion_receipts
#    WHERE completed_at < now() - interval '30 days';
# 行量级: 每完成一个 job 一行, 与队列吞吐同阶, 30 天窗内 ~百万行级以内。
# ---------------------------------------------------------------------------


@router.post("/identity/jobs/error")
async def error_identity_job(
    body: ErrorBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    """discovery worker error: 留 error 行占位, 连击+1(与 pubchem 同通道)。"""
    try:
        return await jobs.fail_identity_job(
            db, job_id=body.job_id, worker_id=worker.worker_id,
            lease_token=body.lease_token, error_code=body.error_code,
            error_detail=body.error_detail)
    except LeaseConflictError as exc:
        raise _lease_conflict_http(exc) from exc
