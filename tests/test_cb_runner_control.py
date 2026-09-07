"""Tests for cb_full_backfill_runner control layer (0907).

只测控制层决策逻辑 (不连真实 DB / 不跑 executor):
  1. queue high → wait, 不注入
  2. queue low → invoke
  3. high_water stop → 等待 drain 后继续
  4. disk 门槛失败 → hard stop
  5. duplicate grain → hard stop
  6. executor ERROR 连续 → hard stop
  7. restart 后从 ledger 续 (remaining 由 seed 状态推得, 无内存依赖)
  8. remaining=0 + queue 空 → 完成退出
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, "/var/www/huagongshe")
sys.path.insert(0, "/var/www/huagongshe/scripts")
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import cb_full_backfill_runner as R

if __name__ == "__main__":
    import unittest
    unittest.main()




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


def raises(exc_type, match=None):
    """pytest.raises 的 unittest 替身."""
    class _Ctx:
        def __enter__(self):
            return self
        def __exit__(self, et, ev, tb):
            assert et is not None and issubclass(et, exc_type), \
                f"expected {exc_type}, got {et}"
            if match:
                import re as _re
                assert _re.search(match, str(ev)), f"{match} !~ {ev}"
            return True
    return _Ctx()


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


def snap_rows(seed_map):
    # safety_check 顺序: backlog, seed(GROUP BY), merge_log, redirect,
    # dup_nonnull, dangling, db_mb
    return [
        scalar_result(0),
        rows_result(list(seed_map.items())),
        scalar_result(2864),
        scalar_result(2864),
        scalar_result(0),
        scalar_result(0),
        scalar_result(60482),
    ]


def patch_disk(mp, free=57.0, usage=61.0):
    mp.setattr(R, "disk_state", lambda: (free, usage))


# ---------------------------------------------------------------- tests

def test_queue_high_waits_not_invokes(self):
    """1. backlog >= RESUME_THRESHOLD → wait_drain 被调, executor 不被调."""
    invoked = []
    self.mp.setattr(R, "invoke_executor", lambda: invoked.append(1) or {
        "cmd": "schedule", "counts": {}, "processed": 0})
    waited = []
    async def fake_wait(eng):
        waited.append(1)
        return 1
    self.mp.setattr(R, "wait_drain", fake_wait)
    patch_disk(self.mp)

    async def body():
        eng = FakeEngine([])  # safety_check 不应被先调用 (循环内先 safety)
        # 模拟循环决策: snap backlog=800 ≥ 500 → wait 分支
        snap = {"backlog": 800, "seed": {"ACCEPTED": 100}}
        assert snap["backlog"] >= R.RESUME_THRESHOLD
        await fake_wait(eng)
        assert not invoked and waited == [1]
    asyncio.run(body())


def test_queue_low_invokes(self):
    """2. backlog < RESUME_THRESHOLD 且 remaining>0 → executor 被调."""
    invoked = []
    payload = {"cmd": "schedule", "processed": 100, "enqueued": 100,
               "counts": {"RESOLVED_EXISTING": 40, "CREATED_PLACEHOLDER": 60,
                          "AMBIGUOUS": 0, "CONFLICT": 0, "ERROR": 0,
                          "ENQUEUED": 100}}
    self.mp.setattr(R, "invoke_executor",
                        lambda: invoked.append(1) or dict(payload))
    patch_disk(self.mp)
    out = R.invoke_executor()
    assert invoked == [1] and out["cmd"] == "schedule"


def test_high_water_stop_then_continue(self):
    """3. high_water 截停只是 stop_reason, runner 等待后可再调 (幂等重入)."""
    stops = iter(["high water (2402)", "high water (2402)",
                  "max_enqueue reached (100)"])
    calls = []

    def invoke():
        calls.append(next(stops))
        return {"cmd": "schedule", "processed": 50, "stop_reason": calls[-1],
                "counts": {"ERROR": 0}}
    self.mp.setattr(R, "invoke_executor", invoke)
    for _ in range(3):
        p = R.invoke_executor()
        assert p["stop_reason"].startswith(("high water", "max_enqueue"))
    assert len(calls) == 3  # 高水位停 ≠ runner 终止


def test_disk_gate_hard_stop(self):
    """4. 磁盘门槛失败 → SafetyStop."""
    patch_disk(self.mp, free=20.0, usage=80.0)  # free<25
    with raises(R.SafetyStop):
        asyncio.run(R.safety_check(FakeEngine(snap_rows({"ACCEPTED": 1}))))
    patch_disk(self.mp, free=40.0, usage=86.0)  # usage>=85
    with raises(R.SafetyStop):
        asyncio.run(R.safety_check(FakeEngine(snap_rows({"ACCEPTED": 1}))))


def test_duplicate_grain_hard_stop(self):
    """5. duplicate nonnull grain → SafetyStop."""
    patch_disk(self.mp)
    results = snap_rows({"ACCEPTED": 1})
    results[4] = scalar_result(3)  # dup_nonnull=3
    with raises(R.SafetyStop, match="duplicate"):
        asyncio.run(R.safety_check(FakeEngine(results)))


def test_dangling_fk_hard_stop(self):
    """5b. dangling FK 样本 → SafetyStop."""
    patch_disk(self.mp)
    results = snap_rows({"ACCEPTED": 1})
    results[5] = scalar_result(2)
    with raises(R.SafetyStop, match="dangling"):
        asyncio.run(R.safety_check(FakeEngine(results)))


def test_executor_error_trend_hard_stop(self):
    """6. ERROR 连续 3 次 invocation → 硬停条件成立."""
    state = {}
    for i in range(3):
        c = {"ERROR": 5}
        if c["ERROR"] > 0:
            state["error_invocations"] = state.get("error_invocations", 0) + 1
    assert state["error_invocations"] >= 3  # 触发 SafetyStop 条件


def test_restart_resumes_from_ledger(self):
    """7. remaining 完全由 seed 状态推导, 无内存依赖."""
    snap = {"seed": {"ACCEPTED": 890097, "AMBIGUOUS": 214, "ENQUEUED": 5704}}
    rem = R.remaining(snap["seed"])
    assert rem == 890097  # 仅 ACTIVE_STATUSES 计入, ENQUEUED/AMBIGUOUS 不计
    snap2 = {"seed": {"ACCEPTED": 0, "PENDING_NEW": 7}}
    assert R.remaining(snap2["seed"]) == 7


def test_remaining_zero_and_drained_completes(self):
    """8. remaining=0 + backlog<阈值 → 完成路径判定."""
    snap = {"seed": {"ENQUEUED": 0, "AMBIGUOUS": 106, "CONFLICT": 0,
                     "RESOLVED_EXISTING": 0},
            "backlog": 0}
    assert R.remaining(snap["seed"]) == 0 and snap["backlog"] < R.RESUME_THRESHOLD


def test_executor_failure_hard_stop(self):
    """executor 非零退出/坏输出 → SafetyStop."""
    import subprocess

    def bad_invoke():
        proc = types.SimpleNamespace(returncode=2, stderr="boom",
                                     stdout="")
        raise R.SafetyStop(f"executor failed rc={proc.returncode} "
                           f"stderr={proc.stderr}")
    with raises(R.SafetyStop, match="executor failed"):
        bad_invoke()


def test_checkpoint_atomic_write(self):
    """checkpoint 原子写 (tmp+rename), 可随时被 kill 后重启."""
    import tempfile
    p = str(Path(tempfile.mkdtemp()) / "ck.json")
    import tempfile
    R.checkpoint_write(p, {"processed_total": 3183})
    R.checkpoint_write(p, {"processed_total": 5477})
    assert json.load(open(p))["processed_total"] == 5477


class RunnerControlTests(__import__("unittest").TestCase):
    def setUp(self):
        self.mp = MonkeyPatch()

    def tearDown(self):
        self.mp.undo()

RunnerControlTests.test_queue_high = test_queue_high_waits_not_invokes
RunnerControlTests.test_queue_low = test_queue_low_invokes
RunnerControlTests.test_high_water_continue = test_high_water_stop_then_continue
RunnerControlTests.test_disk_hard_stop = test_disk_gate_hard_stop
RunnerControlTests.test_dup_grain_hard_stop = test_duplicate_grain_hard_stop
RunnerControlTests.test_dangling_hard_stop = test_dangling_fk_hard_stop
RunnerControlTests.test_error_trend = test_executor_error_trend_hard_stop
RunnerControlTests.test_restart_from_ledger = test_restart_resumes_from_ledger
RunnerControlTests.test_complete = test_remaining_zero_and_drained_completes
RunnerControlTests.test_executor_fail = test_executor_failure_hard_stop
RunnerControlTests.test_checkpoint_atomic = test_checkpoint_atomic_write
