"""caslib.governor — 数据源访问治理(2026-08-29 规范, 见 skill 记录)。

统一原则: 我们的库比对方大, miss 是常态答案不是异常。
四分类语义(全源统一):
  hit    命中     -> 落库
  miss   对方没有 -> 终态, 负缓存, 日级复查
  refuse 拒绝     -> 终态 + 立即停链(封禁页/403/限流页)
  neterr 网络失败 -> 终态, 负缓存, 日级复查
秒级 retry 不存在合法场景; 唯一重试发生在日级轮次(expiry/用户触发)。

Governor 提供:
  1. 连续无命中熔断: 滑动窗内连续 MISS_STREAK 发无命中 -> 冷却源
     COOLDOWN_S(逻辑 bug 全量 miss 时的硬件保险丝, 上限封顶错误流量)
  2. 日预算: 每源每日请求上限, 触顶当日停(持续总量是 8/28 PB 封禁根因)
  3. 健康摘要: 每小时一行 INFO 汇总(发包/命中/miss/熔断/预算),
     补"事后无法重建"的证据缺口

进程内实现(与现有 cpp 熔断同量级): worker 单进程跑单链, 无需跨进程共享;
日预算窗口按本地时区自然日翻转。DB 侧不入表 — 治理是访问层纪律, 不是数据。
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

# ── 参数(按源) ──────────────────────────────────────────────────────────────
# CB: 节奏 ~1-2 rps 串行, 日预算 2万发(现节奏触顶降速, 不放大)
# PB: 解封后 1万/天起步观察(API key 到位后可复核上调)
SOURCE_POLICY: dict[str, dict[str, float]] = {
    "cb": {"miss_streak": 10, "cooldown_s": 1800, "daily_budget": 20_000},
    "pubchem": {"miss_streak": 10, "cooldown_s": 1800, "daily_budget": 10_000},
}


@dataclass
class _SourceState:
    miss_streak: int = 0
    cooldown_until: float = 0.0
    # 日预算(自然日窗口)
    day_start: float = 0.0
    day_requests: int = 0
    # 健康摘要计数(每小时窗)
    summary_start: float = field(default_factory=lambda: _time.monotonic())
    s_requests: int = 0
    s_hit: int = 0
    s_miss: int = 0
    s_refuse: int = 0
    s_neterr: int = 0

    def _roll_day(self, now: float) -> None:
        # 86400s 窗口(单调钟无时区, 翻转语义=滚动24h, 足够近似自然日)
        if now - self.day_start >= 86400:
            self.day_start = now
            self.day_requests = 0


class Governor:
    """每源一个实例; worker 主循环持有, 请求前/后调用。线程不安全(asyncio 单线程用)。"""

    def __init__(self) -> None:
        self._states: dict[str, _SourceState] = {}

    def _state(self, source: str) -> _SourceState:
        if source not in self._states:
            self._states[source] = _SourceState()
            self._states[source].day_start = _time.monotonic()
        return self._states[source]

    # ── 请求前: 允许? ────────────────────────────────────────────────────────
    def allow(self, source: str) -> tuple[bool, str]:
        """返回 (可否发请求, 原因)。False 时调用方不得发请求。

        预算/熔断停链期: 剩余任务一律按"没查"回队延迟(defer, 不产生上游
        流量, 与查询失败不同 — 参照 cpp_circuit_defer 语义)。
        """
        st = self._state(source)
        policy = SOURCE_POLICY.get(source)
        now = _time.monotonic()
        st._roll_day(now)
        if policy is None:
            return True, ""
        if now < st.cooldown_until:
            return False, "cooldown"
        if st.day_requests >= int(policy["daily_budget"]):
            return False, "daily_budget"
        return True, ""

    def record(self, source: str, outcome: str) -> None:
        """请求后上报结果: 'hit' | 'miss' | 'refuse' | 'neterr'。

        refuse = 对方明确拒绝(封禁页/403/限流页) -> 立即停链。
        连续 miss 达阈值 -> 冷却(半开: 冷却期满放行, 下发即探测)。
        """
        st = self._state(source)
        now = _time.monotonic()
        st._roll_day(now)
        st.day_requests += 1
        st.s_requests += 1
        if outcome == "hit":
            st.s_hit += 1
            st.miss_streak = 0
        elif outcome == "miss":
            st.s_miss += 1
            st.miss_streak += 1
            policy = SOURCE_POLICY.get(source)
            if policy and st.miss_streak >= int(policy["miss_streak"]):
                st.cooldown_until = now + policy["cooldown_s"]
                st.miss_streak = 0
        elif outcome == "refuse":
            st.s_refuse += 1
            # 拒绝即停: 冷却窗给上游恢复空间, 半开探测恢复
            policy = SOURCE_POLICY.get(source)
            if policy:
                st.cooldown_until = now + policy["cooldown_s"]
        elif outcome == "neterr":
            st.s_neterr += 1
            # 网络失败也计入 streak — 上游过载的前兆形态之一
            st.miss_streak += 1

    # ── 健康摘要 ─────────────────────────────────────────────────────────────
    def maybe_summary(self, source: str, log, *, interval_s: float = 3600.0) -> None:
        """每小时一行 INFO 汇总。log 需具备 .info()。"""
        st = self._state(source)
        now = _time.monotonic()
        if now - st.summary_start < interval_s:
            return
        budget = SOURCE_POLICY.get(source, {}).get("daily_budget", 0)
        cooldown = "yes" if now < st.cooldown_until else "no"
        log.info(
            "governor[%s] hourly: req=%d hit=%d miss=%d refuse=%d neterr=%d "
            "day_req=%d/%s cooldown=%s",
            source, st.s_requests, st.s_hit, st.s_miss, st.s_refuse, st.s_neterr,
            st.day_requests, int(budget), cooldown,
        )
        st.summary_start = now
        st.s_requests = st.s_hit = st.s_miss = st.s_refuse = st.s_neterr = 0
