"""闸门阶梯(数据链收口§4) — lease 派发口的通道保护。

计数对象=通道(pubchem/cb), 信号源=worker 真实请求结果(error=进, complete=归零)。
阶梯: 连续 5 错→静默 5 分 → 再 2 错→静默 10 分 → 再 1 错→静默 30 分
→ 再 1 错→停止(半开 30 分钟一发, 可自愈)。
计时载体: redis 计数器(streak / silent_until / probe)。零新表。
通道任一 complete → 归零 + gate_unlock_error_rows 整通道 error 行复活。
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


async def gate_halfopen_admit(redis, channel: str, limit: int) -> int:
    """停档期满的半开探测互斥。

    停止档(LADDER 末档, streak ≥ 9)的静默窗自然到期后, 不再整批放行
    (积压 ≥2 时会并发放行多个任务打上游, 背离"到点放行一发"合同):
    streak 仍在停止档时, 第一个到达的 lease 请求获得唯一探测名额
    (redis SET NX 标记, TTL 兜底防 worker 崩溃后卡死半开), 派发上限
    收敛为 1; 其余请求等 5s 重试。成功(gate_record_success)/再失败
    (gate_record_error)都会清除标记, 半开只影响探测窗本身。
    非停止档(streak 不足/已清零)与 redis 故障 → 原上限照常(保守放行)。
    """
    if redis is None or limit <= 0:
        return limit
    try:
        streak = await redis.get(f"gate:{channel}:streak")
        if streak is None or int(streak) < LADDER[-1][0]:
            return limit
        probe = await redis.set(f"gate:{channel}:probe", "1", nx=True, ex=120)
        return 1 if probe else 0
    except Exception:
        return limit


async def gate_record_error(redis, channel: str) -> int:
    """一次 error: 连击+1; 达门槛则设静默窗。返回当前连击数。"""
    if redis is None:
        return 0
    try:
        streak = await redis.incr(f"gate:{channel}:streak")
        # 半开探测失败: 清探测标记, 允许下一静默窗期满后重新半开
        await redis.delete(f"gate:{channel}:probe")
        silence = _silence_for(streak)
        if silence > 0:
            await redis.set(f"gate:{channel}:silent_until", time.time() + silence,
                            ex=silence + 60)
        return streak
    except Exception:
        return 0


async def gate_record_success(redis, channel: str) -> None:
    """一次成功: 通道归零(连击清零, 静默窗解除, 半开探测标记清除)。"""
    if redis is None:
        return
    try:
        await redis.delete(f"gate:{channel}:streak",
                           f"gate:{channel}:silent_until",
                           f"gate:{channel}:probe")
    except Exception:
        pass


# 通道 → 错误行所在表。pubchem 通道含 discovery(identity)链 —— 同通道
# 连击计数, 错误行必须同随通道恢复复活(通道解锁即错误复活:
# 此前只翻 pubchem_jobs/cas_jobs, pubchem_identity_jobs 的 error 行
# 不随通道恢复复活, 与"通道成功解锁"的注释语义相悖)。
_CHANNEL_ERROR_TABLES: dict[str, tuple[str, ...]] = {
    "pubchem": ("pubchem_jobs", "pubchem_identity_jobs"),
    "cb": ("cas_jobs",),
}


async def gate_unlock_error_rows(db, channel: str) -> None:
    """通道成功后: 该通道 error 行全部复活归队。"""
    from sqlalchemy import text
    for table in _CHANNEL_ERROR_TABLES[channel]:
        await db.execute(text(f"""
            UPDATE maintenance.{table}
            SET status='queued', updated_at=now()
            WHERE status='error'
        """))
