"""对外数据服务: 授权凭证的签名请求校验。

独立于站内其他接口的鉴权体系: 自有凭证表、HMAC 请求签名、时间窗与
nonce 防重放、按 (method, path) 的 scope 精确映射。请求要素:

    Authorization: Bearer <令牌>
    X-Client-Id:   <client_id>
    X-Timestamp:   <unix 秒>
    X-Nonce:       <一次性随机串>
    X-Signature:   hex(HMAC-SHA256(令牌, 签名消息))

签名消息(各要素用 "\\n" 连接, 依序):

    METHOD
    PATH            (不含查询串, 如 /data/v1/chemicals/996)
    QUERY           (原始查询串, 无查询时为空; 顺序敏感)
    BODY_SHA256     (hex(sha256(请求体)); GET 为 hex(sha256(b"")) )
    TIMESTAMP       (与 X-Timestamp 同值)
    NONCE           (与 X-Nonce 同值)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from ...core.cache import current_pool

# 时间窗: 请求时间戳与服务器的偏差上限(秒)。
TIMESTAMP_TOLERANCE_SECONDS = 300
# nonce 防重放窗口(秒): 略大于时间窗, 窗口过后键自动过期。
NONCE_TTL_SECONDS = TIMESTAMP_TOLERANCE_SECONDS * 2

CHEMICAL_READ_SCOPE = "data:chemical:read"
REACTION_READ_SCOPE = "data:reaction:read"
# 能力位（不映射路径）：允许 lookup 未收录时触发采集/建行。只读凭证
# （仅 data:chemical:read）的 lookup 是纯读 —— 未收录即 not_found，
# 不创建化合物行、不提交采集任务。需触发采集的凭证另授此 scope。
CHEMICAL_INGEST_SCOPE = "data:chemical:ingest"

# scope → 允许的 (method, path) 精确映射; 未登记的路径一律拒绝。
SCOPE_PATHS: dict[str, set[tuple[str, str]]] = {
    CHEMICAL_READ_SCOPE: {
        ("GET", "/data/v1/chemicals/{hcid}"),
        ("GET", "/data/v1/chemicals"),
        ("GET", "/data/v1/chemicals/lookup"),
        ("GET", "/data/v1/chemicals/{hcid}/reactions"),
    },
    REACTION_READ_SCOPE: {
        ("GET", "/data/v1/reactions/{hrid}"),
        ("GET", "/data/v1/reactions"),
    },
}


class DataApiAuthError(Exception):
    """鉴权失败; code 为对外错误码。"""

    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class DataClient:
    id: int
    client_id: str
    scopes: list[str]
    rate_per_minute: int
    rate_per_day: int


def sign_message(method: str, path: str, query: str, body_sha256: str,
                 timestamp: str, nonce: str) -> bytes:
    """构造签名消息(各要素用换行连接, 依序拼接)。"""
    return "\n".join([method.upper(), path, query, body_sha256, timestamp, nonce]).encode()


def compute_signature(token: str, message: bytes) -> str:
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def body_sha256_hex(body: bytes | None) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def generate_token() -> str:
    return "hgsd_" + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def load_client(db: Any, client_id: str, token: str) -> DataClient:
    """按 client_id + 令牌哈希取凭证; 校验启用状态与到期时间。"""
    row = (await db.execute(text("""
        SELECT id, client_id, scopes, rate_per_minute, rate_per_day,
               enabled, expires_at
        FROM data_api.clients
        WHERE client_id = :cid AND token_hash = :th
    """), {"cid": client_id, "th": token_hash(token)})).fetchone()
    if row is None:
        raise DataApiAuthError("unauthorized", "凭证无效")
    if not row[5]:
        raise DataApiAuthError("unauthorized", "凭证已停用")
    # expires_at 为 PG timestamptz → 带时区 datetime；与 time.time() 浮点
    # 直接比较会 TypeError（被外层吞成服务不可用，未到期凭证也无法使用）。
    if row[6] is not None and row[6] < datetime.now(timezone.utc):
        raise DataApiAuthError("unauthorized", "凭证已到期")
    return DataClient(
        id=row[0], client_id=row[1], scopes=list(row[2]),
        rate_per_minute=row[3], rate_per_day=row[4])


def verify_signature(client_token: str, *, method: str, path: str, query: str,
                     body: bytes | None, timestamp: str, nonce: str,
                     signature: str, now: float | None = None) -> None:
    """时间窗、签名、nonce 三道校验(依序); 任一失败抛 DataApiAuthError。"""
    current = now if now is not None else time.time()
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise DataApiAuthError("unauthorized", "时间戳格式不正确") from None
    if abs(current - ts) > TIMESTAMP_TOLERANCE_SECONDS:
        raise DataApiAuthError("unauthorized", "请求时间超出允许偏差")

    expected = compute_signature(
        client_token,
        sign_message(method, path, query, body_sha256_hex(body), timestamp, nonce))
    if not hmac.compare_digest(expected, (signature or "").lower()):
        raise DataApiAuthError("unauthorized", "签名不正确")


async def check_nonce(client_id: str, nonce: str) -> None:
    """nonce 防重放: 窗口内同一凭证的 nonce 只能用一次。

    Redis 异常时拒绝请求(fail-closed): 防重放不可绕过。
    """
    import redis.asyncio as redis

    client = redis.Redis(connection_pool=current_pool())
    key = f"data-api-nonce:{client_id}:{hashlib.sha256(nonce.encode()).hexdigest()}"
    try:
        stored = await client.set(key, "1", ex=NONCE_TTL_SECONDS, nx=True)
    except Exception as exc:
        raise DataApiAuthError("unavailable", "防重放服务暂时不可用", status=503) from exc
    if not stored:
        raise DataApiAuthError("replayed_request", "重复的请求")


def authorize_scope(client: DataClient, method: str, path_template: str) -> None:
    """(method, 路径模板) 必须落在凭证 scope 的精确映射内。"""
    wanted = (method.upper(), path_template)
    for scope in client.scopes:
        if wanted in SCOPE_PATHS.get(scope, set()):
            return
    raise DataApiAuthError("forbidden_scope", "凭证未授权该接口", status=403)
