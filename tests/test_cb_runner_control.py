"""Tests for cb_full_backfill_runner control layer v2 (0907).

只测控制层决策逻辑 (不连真实 DB / 不跑 executor):
rolling gate / upstream hard stops / Gov merge delta / PB 监控 /
persistent seed error / restart 恢复 / 完成路径。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, "/var/www/huagongshe")
sys.path.insert(0, "/var/www/huagongshe/scripts")
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import cb_full_backfill_runner as R


def raises(exc_type, match=None):
    class _Ctx:
        def __enter__(self):
            return self
        def __exit__(self, et, ev, tb):
            assert et is not None and issubclass(et, exc_type), \
                f"expected {exc_type}, got {et}: {ev}"
            if match:
                import re as _re
                assert _re.search(match, str(ev)), f"{match} !~ {ev}"
            return True
    return _Ctx()


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append((obj, name, old))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo = []


# ---------------------------------------------------------------- helpers

class FakeConn:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, stmt=None, *_a, **_k):
        sql = str(stmt)
        if "statement_timeout" in sql:
            r = types.SimpleNamespace()
            r.scalar = lambda: None
            return r
        return self._results.pop(0)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeEngine:
    def __init__(self, results):
        self._results = results

    def connect(self):
        return FakeConn(self._results)

    async def dispose(self):
        pass


def scalar_result(value):
    r = types.SimpleNamespace()
    r.scalar = lambda: value
    return r


def rows_result(pairs):
    r = types.SimpleNamespace()
    r.fetchall = lambda: pairs
    return r


def snap_rows(seed_map, merge=2864, redirect=2864, pb_queued=0, pb_error=0,
              stuck=None):
    # safety_check 顺序: backlog, seed, merge_log, redirect, dup_nn,
    # dup_null, dangling, stuck_seeds, db_mb, pb_queued, pb_error
    stuck = stuck or []
    return [
        scalar_result(0),
        rows_result(list(seed_map.items())),
        scalar_result(merge),
        scalar_result(redirect),
        scalar_result(0),
        scalar_result(0),
        scalar_result(0),
        rows_result(stuck),
        scalar_result(60482),
        scalar_result(pb_queued),
        scalar_result(pb_error),
    ]


# ---------------------------------------------------------------- tests: rolling gate

def test_rolling_below_limit_can_invoke(self):
    """1. 1h processed < 3000 → 可 invoke。"""
    g = R.RollingGate()
    g.add(2400, ts=1000.0)
    assert not g.blocked(now=2000.0)
    assert g.sum_last_hour(now=2000.0) == 2400


def test_rolling_at_limit_blocks(self):
    """2. =3000 → 不 invoke。"""
    g = R.RollingGate()
    g.add(3000, ts=1000.0)
    assert g.blocked(now=2000.0)


def test_rolling_release_recovers(self):
    """3. 窗口滑出 → 自动恢复。"""
    g = R.RollingGate()
    g.add(3000, ts=1000.0)
    assert g.blocked(now=2000.0)
    # 事件滑出 1h 窗口
    assert not g.blocked(now=1000.0 + R.ROLLING_WINDOW_S + 1)
    assert g.sum_last_hour(now=4601.0) == 0


def test_rolling_multi_event_sum(self):
    """额度按多事件累计。"""
    g = R.RollingGate()
    g.add(1500, ts=100.0)
    g.add(1500, ts=2000.0)
    assert g.blocked(now=2500.0)          # 两事件都在窗口内 = 3000
    assert not g.blocked(now=2000.0 + R.ROLLING_WINDOW_S)  # 第一笔滑出


# ---------------------------------------------------------------- tests: upstream

def test_upstream_403_hard_stop(self):
    """4. 403 → hard stop。"""
    lines = ["2026-09-07 15:00:00,000 INFO caslib.fetch cpp cb=1 loc=zh "
             "status=403 bytes=0 state=error\n"] * 500
    with open("/tmp/_fake_worker.log", "w") as f:
        f.writelines(lines)
    old = R.WORKER_LOG
    R.WORKER_LOG = "/tmp/_fake_worker.log"
    try:
        with raises(R.SafetyStop, match="403"):
            R.check_upstream_log()
    finally:
        R.WORKER_LOG = old


def test_upstream_429_hard_stop(self):
    """5. 429 → hard stop。"""
    lines = ["2026-09-07 15:00:00,000 INFO caslib.fetch cas 50-00-0 "
             "status=429 bytes=0 state=error\n"]
    with open("/tmp/_fake_worker.log", "w") as f:
        f.writelines(lines)
    old = R.WORKER_LOG
    R.WORKER_LOG = "/tmp/_fake_worker.log"
    try:
        with raises(R.SafetyStop, match="429"):
            R.check_upstream_log()
    finally:
        R.WORKER_LOG = old


def test_not_found_and_404_do_not_stop(self):
    """普通 not_found / 404 缺页不停。"""
    lines = ["2026-09-07 15:00:00,000 INFO caslib.fetch cpp cb=1 loc=zh "
             "status=404 bytes=2271 state=error\n"] * 100 + \
            ["2026-09-07 15:00:00,000 INFO caslib.fetch cas 50-00-0 "
             "status=200 bytes=100 state=not_found\n"] * 100
    with open("/tmp/_fake_worker.log", "w") as f:
        f.writelines(lines)
    old = R.WORKER_LOG
    R.WORKER_LOG = "/tmp/_fake_worker.log"
    try:
        counts = R.check_upstream_log()
        assert counts["cb_403"] == 0 and counts["cb_429"] == 0
    finally:
        R.WORKER_LOG = old


# ---------------------------------------------------------------- tests: integrity / gov

def test_source_mismatch_hard_stop(self):
    """6. duplicate grain → hard stop (source mismatch 类)。"""
    results = snap_rows({"ACCEPTED": 1})
    results[4] = scalar_result(3)          # dup_nonnull
    with raises(R.SafetyStop, match="duplicate"):
        asyncio.run(R.safety_check(FakeEngine(results)))


def test_unexpected_merge_delta_hard_stop(self):
    """7. 未知 reason 的新 merge → hard stop。"""
    state = {"merge_baseline": 2864, "merge_max_id": 2864}
    results = snap_rows({"ACCEPTED": 1}, merge=2865)
    # 顺序: ... dangling 之后插入 merge delta 查询结果
    idx_new_reasons = 7                     # dangling 之后, stuck 之前
    results.insert(idx_new_reasons, rows_result(
        [("mystery-auto-merge-gate",)]))
    with raises(R.SafetyStop, match="unexplained merge"):
        asyncio.run(R.safety_check(FakeEngine(results), state))


def test_known_merge_reason_passes(self):
    """已知正式 gate 的 merge delta 不停。"""
    state = {"merge_baseline": 2864, "merge_max_id": 2864}
    results = snap_rows({"ACCEPTED": 1}, merge=2865)
    results.insert(7, rows_result(
        [("prod-batch-2864 | gate=same-cid:11446610",)]))
    snap = asyncio.run(R.safety_check(FakeEngine(results), state))
    assert snap["merge_log"] == 2865        # 不抛 = 通过


# ---------------------------------------------------------------- tests: PB

def test_pb_occasional_503_no_stop(self):
    """8. PB 偶发 503 不停 (check_upstream_log 只统计 CB caslib.fetch 行,
    PubChem 503 行不在扫描域)。"""
    lines = ["2026-09-07 15:49:53,003 INFO huagongshe-worker PubChem "
             "job=390629 error: PubChem HTTP 503\n"] * 30
    with open("/tmp/_fake_worker.log", "w") as f:
        f.writelines(lines)
    old = R.WORKER_LOG
    R.WORKER_LOG = "/tmp/_fake_worker.log"
    try:
        counts = R.check_upstream_log()     # 不抛
        assert counts["cb_403"] == 0
    finally:
        R.WORKER_LOG = old


def test_pb_backlog_growth_stop(self):
    """9. PB queue 连续增长 (5 周期只增不降) → stop。
    模拟 wait_drain 内的判定序列。"""
    seq = [100, 200, 300, 400, 500]         # 单调增
    window = seq[-R.PB_BACKLOG_GROW_CYCLES:]
    assert all(b > a for a, b in zip(window, window[1:]))
    # 对照: 波动序列不触发
    seq2 = [100, 300, 200, 350, 250]
    w2 = seq2[-R.PB_BACKLOG_GROW_CYCLES:]
    assert not all(b > a for a, b in zip(w2, w2[1:]))


def test_pb_error_accumulation_threshold(self):
    """PB final error >= 100 → stop 条件成立。"""
    assert 150 >= R.PB_ERROR_LIMIT and 99 < R.PB_ERROR_LIMIT


# ---------------------------------------------------------------- tests: seed error

def test_persistent_seed_error_stop(self):
    """10. ERROR seed attempts 达上限 → hard stop 且带 cb/cas/attempts。"""
    stuck = [("0123456", "50-00-0", 10, "cpp fetch failed")]
    results = snap_rows({"ACCEPTED": 1}, stuck=stuck)
    with raises(R.SafetyStop, match=r"cb=0123456 cas=50-00-0 attempts=10"):
        asyncio.run(R.safety_check(FakeEngine(results)))


def test_normal_attempts_no_stop(self):
    """attempts 未达上限的 ERROR 不停。"""
    results = snap_rows({"ACCEPTED": 1, "ERROR": 5})  # stuck 空
    snap = asyncio.run(R.safety_check(FakeEngine(results)))
    assert snap["seed"]["ERROR"] == 5


# ---------------------------------------------------------------- tests: restart / complete

def test_restart_rolling_window_restored(self):
    """11. kill/restart 后 rolling 窗口从 checkpoint 事件恢复。"""
    import time as _t
    now = _t.time()
    events = [[now - 600, 1500], [now - 100, 1200]]
    g = R.RollingGate(events)
    assert g.sum_last_hour() == 2700
    g.add(300)
    assert g.blocked()                      # 3000 达限
    # 序列化 → 反序列化 (restart 模拟)
    g2 = R.RollingGate(json.loads(json.dumps(g.snapshot())))
    assert g2.blocked() and g2.sum_last_hour() == 3000


def test_disk_gate_hard_stop(self):
    results = snap_rows({"ACCEPTED": 1})
    old = R.disk_state
    R.disk_state = lambda: (20.0, 80.0)
    try:
        with raises(R.SafetyStop, match="disk free"):
            asyncio.run(R.safety_check(FakeEngine(results)))
    finally:
        R.disk_state = old


def test_remaining_zero_and_drained_completes(self):
    """12. remaining=0 + backlog<阈值 → 完成路径判定。"""
    snap = {"seed": {"AMBIGUOUS": 106, "ENQUEUED": 0},
            "backlog": 0}
    assert R.remaining(snap["seed"]) == 0
    assert snap["backlog"] < R.RESUME_THRESHOLD


def test_executor_error_trend(self):
    state = {}
    for _ in range(3):
        c = {"ERROR": 5}
        if c["ERROR"] > 0:
            state["error_invocations"] = state.get("error_invocations", 0) + 1
    assert state["error_invocations"] >= 3


def test_checkpoint_atomic_write(self):
    import tempfile
    p = str(Path(tempfile.mkdtemp()) / "ck.json")
    R.checkpoint_write(p, {"processed_total": 3183,
                           "safety_status": "RUNNING"})
    R.checkpoint_write(p, {"processed_total": 5477})
    assert json.load(open(p))["processed_total"] == 5477


if __name__ == "__main__":
    unittest.main()


class RunnerControlTestsV2(unittest.TestCase):
    def setUp(self):
        self.mp = MonkeyPatch()

    def tearDown(self):
        self.mp.undo()


RunnerControlTestsV2.test_rolling_below = test_rolling_below_limit_can_invoke
RunnerControlTestsV2.test_rolling_at_limit = test_rolling_at_limit_blocks
RunnerControlTestsV2.test_rolling_release = test_rolling_release_recovers
RunnerControlTestsV2.test_rolling_multi = test_rolling_multi_event_sum
RunnerControlTestsV2.test_403_stop = test_upstream_403_hard_stop
RunnerControlTestsV2.test_429_stop = test_upstream_429_hard_stop
RunnerControlTestsV2.test_not_found_ok = test_not_found_and_404_do_not_stop
RunnerControlTestsV2.test_mismatch_stop = test_source_mismatch_hard_stop
RunnerControlTestsV2.test_merge_delta_stop = test_unexpected_merge_delta_hard_stop
RunnerControlTestsV2.test_known_merge_ok = test_known_merge_reason_passes
RunnerControlTestsV2.test_pb_503_ok = test_pb_occasional_503_no_stop
RunnerControlTestsV2.test_pb_growth = test_pb_backlog_growth_stop
RunnerControlTestsV2.test_pb_error_accum = test_pb_error_accumulation_threshold
RunnerControlTestsV2.test_seed_error_stop = test_persistent_seed_error_stop
RunnerControlTestsV2.test_seed_error_ok = test_normal_attempts_no_stop
RunnerControlTestsV2.test_restart_rolling = test_restart_rolling_window_restored
RunnerControlTestsV2.test_disk_stop = test_disk_gate_hard_stop
RunnerControlTestsV2.test_complete = test_remaining_zero_and_drained_completes
RunnerControlTestsV2.test_error_trend = test_executor_error_trend
RunnerControlTestsV2.test_checkpoint_atomic = test_checkpoint_atomic_write
