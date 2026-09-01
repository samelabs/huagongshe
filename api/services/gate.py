"""闸门阶梯(数据链收口§4) — lease 派发口的通道保护。

计数对象=通道(pubchem/cb), 信号源=worker 真实请求结果(error=进, complete=归零)。
阶梯(定案): 连续 5 错→静默 5 分 → 再 2 错→静默 10 分 → 再 1 错→静默 30 分
→ 再 1 错→停止(半开 30 分钟一发, 可自愈)。
计时载体: redis 计数器 + error 行 not_before(阶梯档时间)。零新表。
redis 缺席=无闸门(保守放行); API 重启计数丢失=从第一档重爬(保守方向)。
lease 过期回收不进计数(本地问题非通道问题)。
"""

from __future__ import annotations

import time

# (进入档位所需累计连续错误数, 静默秒数); 第4档起为停止档: 每次静默 30 分钟,
# 到点放行一发(半开探测=真实 job), 不通再静默 30 分 — 自愈无独立机制。
# 累计数是"进入该档的门槛": 5 错进 1 档, 7 错进 2 档, 8 错进 3 档, 9 错停止。
LADDER: tuple[tuple[int, int], ...] = (
    (5, 5 * 60),
    (7, 10 * 60),
    (8, 30 * 60),
    (9, 30 * 60),
)


def _silence_for(streak: int) -> int:
    """给定连续错误数, 返回应静默的秒数(0=不静默)。"""
    silence = 0
    for threshold, secs in LADDER:
        if streak >= threshold:
            silence = secs
    return silence


async def gate_silence_remaining(redis, channel: str) -> float:
    """通道静默剩余秒数; >0 则 lease 不派发。redis 缺席=0(放行)。"""
    if redis is None:
        return 0.0
    try:
        until = await redis.get(f"gate:{channel}:silent_until")
        if not until:
            return 0.0
        remaining = float(until) - time.time()
        return remaining if remaining > 0 else 0.0
    except Exception:
        return 0.0


async def gate_record_error(redis, channel: str) -> int:
    """一次 error: 连击+1; 达门槛则设静默窗。返回当前连击数。"""
    if redis is None:
        return 0
    try:
        streak = await redis.incr(f"gate:{channel}:streak")
        silence = _silence_for(streak)
        if silence > 0:
            await redis.set(f"gate:{channel}:silent_until", time.time() + silence,
                            ex=silence + 60)
        return streak
    except Exception:
        return 0


async def gate_record_success(redis, channel: str) -> None:
    """一次成功: 通道归零(连击清零, 静默窗解除)。"""
    if redis is None:
        return
    try:
        await redis.delete(f"gate:{channel}:streak", f"gate:{channel}:silent_until")
    except Exception:
        pass


async def gate_unlock_error_rows(db, channel: str) -> None:
    """通道成功后: 该通道 error 行全部复活归队(0901 终版语义, 纯翻态无时间字段)。"""
    from sqlalchemy import text
    table = "pubchem_jobs" if channel == "pubchem" else "cas_jobs"
    await db.execute(text(f"""
        UPDATE maintenance.{table}
        SET status='queued', updated_at=now()
        WHERE status='error'
    """))
