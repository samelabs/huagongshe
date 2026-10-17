"""对外数据服务: 按凭证计量(每分钟/每天)与每日用量记录。

只按凭证分桶, 不按 IP, 没有全站共享桶; 超额返回 429 并带 Retry-After。
用量记录失败只记日志, 不影响请求。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import text

from ...core import rate_limit
from .auth import DataApiAuthError, DataClient

logger = logging.getLogger(__name__)

MINUTE_BUCKET = "data-api-minute"
DAY_BUCKET = "data-api-day"


async def enforce_quota(client: DataClient) -> None:
    """每分钟与每天两道额度; 超额抛 429 语义错误。"""
    try:
        await rate_limit.enforce(MINUTE_BUCKET, str(client.id), client.rate_per_minute, 60)
        await rate_limit.enforce(DAY_BUCKET, str(client.id), client.rate_per_day, 86400)
    except rate_limit.RateLimited as exc:
        raise DataApiAuthError(
            "rate_limited", "已超出该凭证的调用额度", status=429) from exc
    except rate_limit.RateLimitError as exc:
        raise DataApiAuthError(
            "unavailable", "计量服务暂时不可用", status=503) from exc


async def record_usage(db: Any, client_id: int, *, error: bool = False) -> None:
    """按天累计调用量/错误量; 失败容忍。"""
    try:
        await db.execute(text("""
            INSERT INTO data_api.usage_daily(client_id, day, calls, errors)
            VALUES (:cid, :day, 1, :err)
            ON CONFLICT (client_id, day)
            DO UPDATE SET calls = data_api.usage_daily.calls + 1,
                          errors = data_api.usage_daily.errors + :err
        """), {"cid": client_id, "day": date.today(), "err": 1 if error else 0})
        await db.commit()
    except Exception:  # noqa: BLE001 — 计量记录失败不影响请求
        await db.rollback()
        logger.warning("data api usage recording failed", exc_info=True)
