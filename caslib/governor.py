"""caslib.governor — 数据源访问治理(2026-08-29 规范, 见 skill 记录)。

统一原则: 治理对象是 worker 与上游的交互 — 响应分类 + 节流闭环 + 停链/半开恢复。

四分类语义(全源统一):
  hit    命中     -> 落库
  miss   对方没有 -> 任务终态, 负缓存, 日级复查
  refuse 拒绝     -> 任务终态 + 立即停链(封禁页/403/限流页), 半开探测恢复
  neterr 网络失败 -> 任务终态; 连续 N 个 = 上游过载信号 -> 冷却

秒级 retry 不存在合法场景(lease 过期回队是 attempt 唯一合法用途)。
无总量限制(日预算已删 — 总量不是治理对象, 交互才是)。

Governor 提供(进程内, worker 单实例用):
  1. 连续无命中熔断: MISS_STREAK 发连续 miss/neterr -> 冷却源 COOLDOWN_S
     (上游过载/逻辑 bug 全量 miss 时的探测保险丝, 半开恢复)
  2. refuse 即停链 + 半开探测恢复(恢复由上游响应批准, 不由时钟)
  3. 健康摘要: 每小时一行 INFO(发包/命中/miss/refuse/neterr/停链态)
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

# ── 参数(按源) ──────────────────────────────────────────────────────────────
SOURCE_POLICY: dict[str, dict[str, float]] = {
    # CB 是网页抓取, 上游无信号; 过载信号只有"系统忙"页, 由 fetch 层
    # cpp 熔断(连续5次busy→600s)承担。governor 对 cb 不设策略 —
    # not_found 是"对方没有"的答案, 不是过载信号, 不得据此停链。
    "pubchem": {"miss_streak": 10, "cooldown_s": 1800},
}


@dataclass
class _SourceState:
    miss_streak: int = 0
    cooldown_until: float = 0.0
    # 健康摘要计数(每小时窗)
    summary_start: float = field(default_factory=lambda: _time.monotonic())
    s_requests: int = 0
    s_hit: int = 0
    s_miss: int = 0
    s_refuse: int = 0
    s_neterr: int = 0


class Governor:
    """每源一个实例; worker 主循环持有, 请求前/后调用。asyncio 单线程用。"""

    def __init__(self) -> None:
        self._states: dict[str, _SourceState] = {}

    def _state(self, source: str) -> _SourceState:
        if source not in self._states:
            self._states[source] = _SourceState()
        return self._states[source]

    # ── 请求前: 允许? ────────────────────────────────────────────────────────
    def allow(self, source: str) -> tuple[bool, str]:
        """返回 (可否发请求, 原因)。False 时调用方不得发请求。

        停链期剩余任务按"没查"回队延迟(defer, 不产生上游流量)。
        冷却期满即半开: 放行下一发当探测。
        """
        st = self._state(source)
        if _time.monotonic() < st.cooldown_until:
            return False, "cooldown"
        return True, ""

    def record(self, source: str, outcome: str) -> None:
        """请求后上报: 'hit' | 'miss' | 'refuse' | 'neterr'。

        refuse(明确拒绝) -> 立即停链, 半开探测恢复。
        连续 miss/neterr 达阈值 -> 冷却(上游过载探测器)。
        hit 清零 streak。
        """
        st = self._state(source)
        now = _time.monotonic()
        policy = SOURCE_POLICY.get(source)
        st.s_requests += 1
        if outcome == "hit":
            st.s_hit += 1
            st.miss_streak = 0
        elif outcome == "miss":
            st.s_miss += 1
            st.miss_streak += 1
            if policy and st.miss_streak >= int(policy["miss_streak"]):
                st.cooldown_until = now + policy["cooldown_s"]
                st.miss_streak = 0
        elif outcome == "refuse":
            st.s_refuse += 1
            if policy:
                st.cooldown_until = now + policy["cooldown_s"]
        elif outcome == "neterr":
            st.s_neterr += 1
            st.miss_streak += 1

    # ── 健康摘要 ─────────────────────────────────────────────────────────────
    def maybe_summary(self, source: str, log, *, interval_s: float = 3600.0) -> None:
        """每小时一行 INFO 汇总。log 需具备 .info()。"""
        st = self._state(source)
        now = _time.monotonic()
        if now - st.summary_start < interval_s:
            return
        halted = "yes" if now < st.cooldown_until else "no"
        log.info(
            "governor[%s] hourly: req=%d hit=%d miss=%d refuse=%d neterr=%d halted=%s",
            source, st.s_requests, st.s_hit, st.s_miss, st.s_refuse, st.s_neterr,
            halted,
        )
        st.summary_start = now
        st.s_requests = st.s_hit = st.s_miss = st.s_refuse = st.s_neterr = 0
