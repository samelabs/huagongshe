"""Pipeline 健康模型 (A1 0912) — 唯一判定点, 前端只渲染不判定。

语义(输入全部来自真实数据, 不凭感觉):

healthy    worker 在线(覆盖该链 scope 且心跳新鲜) 且 近期有成功写入(成功窗口内)
idle       无 backlog、无 active lease、worker 在线但近期无写入 —— 正常
backlogged queued>0 且 worker 在线(仍有处理能力)
stalled    queued>0 且 无在线 worker 覆盖该链(或全 worker 离线)
degraded   error>0 或 gate 静默中 或 该链关键指标不可用

优先级: unavailable > stalled > backlogged > degraded > healthy > idle。
(一个链既 backlogged 又在报错 → backlogged: 队列堆积是更需操作的信号;
 但指标不可用时绝不能伪装 healthy。)

在线阈值依据(代码事实, 非拍脑袋):
- worker 每次请求 workapi 都会刷新 last_seen, 但持久化被 redis 节流
  (workapi.py: `workapi:last-seen:{id}` EX=300 NX) → 最长 5 分钟才落一次库;
- CB 心跳 interval = max(20, lease_seconds//3) = 60s; PB lease 180s 整包。
- 因此 last_seen_at 落库延迟最坏 ≈ 300s(节流窗) + 60s(下次请求间隔)。
  阈值 = 600s: >10 分钟无 DB 心跳即 offline; 300~600s = stale(节流窗内,
  无法区分"在跑但没落库"与"刚掉线", 如实标 stale)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# 在线判定阈值(秒) — 由 workapi last_seen 节流(300s EX)+心跳间隔(60s)推得
WORKER_OFFLINE_S = 600
WORKER_STALE_S = 300

# "近期成功写入"窗口(秒): 该窗口内有落库即视为活跃
RECENT_SUCCESS_S = 3600


@dataclass
class WorkerRuntime:
    worker_id: str
    display_name: str | None
    enabled: bool
    scopes: list[str]
    last_seen_at: datetime | None
    # runtime projection: online / stale / offline / disabled
    runtime: str
    last_seen_age_s: float | None


def worker_runtime_status(
    enabled: bool, last_seen_at: datetime | None, now: datetime,
) -> tuple[str, float | None]:
    """enabled 与 online 严格分离。

    enabled=False → disabled(管理端停权, 与进程无关)。
    无心跳记录 → offline。age>WORKER_OFFLINE_S → offline。
    age>WORKER_STALE_S → stale(心跳落库节流窗内, 无法确证)。
    其余 → online。
    """
    if not enabled:
        return "disabled", None
    if last_seen_at is None:
        return "offline", None
    # datetime 可能带 tzinfo(DB timestamptz)也可能不带(测试构造), 归一化
    ls = last_seen_at if last_seen_at.tzinfo else last_seen_at.replace(tzinfo=timezone.utc)
    nw = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age = max(0.0, (nw - ls).total_seconds())
    if age > WORKER_OFFLINE_S:
        return "offline", age
    if age > WORKER_STALE_S:
        return "stale", age
    return "online", age


def build_worker_runtimes(
    rows: list[tuple[str, str | None, bool, list[str], datetime | None]],
    now: datetime,
) -> list[WorkerRuntime]:
    """rows: (worker_id, display_name, enabled, scopes, last_seen_at)。"""
    out: list[WorkerRuntime] = []
    for worker_id, display_name, enabled, scopes, last_seen_at in rows:
        runtime, age = worker_runtime_status(enabled, last_seen_at, now)
        out.append(WorkerRuntime(
            worker_id=worker_id, display_name=display_name, enabled=enabled,
            scopes=list(scopes or []), last_seen_at=last_seen_at,
            runtime=runtime, last_seen_age_s=age,
        ))
    return out


def _chain_has_online_worker(
    runtimes: list[WorkerRuntime], scope: str,
) -> bool:
    """存在 enabled 且 runtime ∈ {online, stale} 且 scopes 覆盖该链的 worker。

    stale 也算"可能在线": 600s 内仍可能只是节流窗没落库;
    判 stalled 需要更强证据(>10 分钟无心跳)。
    """
    return any(
        w.enabled and w.runtime in ("online", "stale") and scope in w.scopes
        for w in runtimes
    )


def chain_health(
    *,
    scope: str,
    queued: int,
    leased: int,
    error: int,
    latest_success_at: datetime | None,
    gate_silent: bool,
    metrics_available: bool,
    worker_runtimes: list[WorkerRuntime],
    now: datetime,
) -> dict[str, Any]:
    """单链健康判定。返回 {status, has_online_worker, recent_success,
    oldest_queued_age_s?(透传), reasons[]}。

    依据字段全部显式传入, 本函数零 I/O → 可直接单测。
    """
    has_worker = _chain_has_online_worker(worker_runtimes, scope)

    recent_success = False
    if latest_success_at is not None:
        ls = latest_success_at if latest_success_at.tzinfo else \
            latest_success_at.replace(tzinfo=timezone.utc)
        nw = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        recent_success = (nw - ls).total_seconds() <= RECENT_SUCCESS_S

    reasons: list[str] = []
    if not metrics_available:
        status = "unavailable"
        reasons.append("关键指标不可用")
    elif queued > 0 and not has_worker:
        status = "stalled"
        reasons.append(f"队列 {queued} 条积压, 无在线 worker 覆盖 {scope} 链")
    elif queued > 0 and has_worker:
        status = "backlogged"
        reasons.append(f"队列 {queued} 条积压, worker 在线消化中")
    elif not has_worker and queued == 0:
        # 无 worker 但也无积压: 不慌, 但也不是 healthy(没有处理能力)
        status = "idle" if not recent_success else "idle"
        reasons.append("无积压, 无在线 worker")
    elif recent_success:
        status = "healthy"
    else:
        status = "idle"
        reasons.append("无积压, 近期无写入")

    # degraded 叠加: error 留痕 / gate 静默 —— 只把 healthy 降级;
    # backlogged 保留(堆积比报错更需操作, error 信息仍在 error_buckets 可见),
    # idle 不降级(空闲期旧留痕不代表当前异常)。
    if status == "healthy":
        if error > 0:
            status = "degraded"
            reasons.append(f"error 留痕 {error} 条")
        elif gate_silent:
            status = "degraded"
            reasons.append("闸门静默中")

    return {
        "status": status,
        "has_online_worker": has_worker,
        "recent_success": recent_success,
        "reasons": reasons,
    }
