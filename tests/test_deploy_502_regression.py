"""E8 502 回归测试 —— 部署全过程中不得出现 "active upstream target 无 live ready generation"。

判定点比"命令调用顺序"更强: 整个部署过程(含所有失败窗口)持续采样 traffic probe,
断言不存在 `old stopped + new not ready + traffic 仍指向死 upstream` 的状态。

为了证明这个判定点真的能抓住旧缺陷, 同一套采样器也跑一遍**旧行为**
(先停旧代再起新代 = fork 模式下 `pm2 reload` + 固定端口 nginx), 断言旧行为必然被记为 violation。
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.deploy import GENERATIONS, Deployer  # noqa: E402
from tests.deploy_fakes import (  # noqa: E402
    FakeProber,
    FakeRunner,
    FakeWorld,
    TrafficMonitor,
    legacy_restart_sequence,
    make_env,
    write_active_link,
)


class Regression502Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.paths = make_env(self.tmp)
        self.world = FakeWorld()
        self.world.start("blue")
        write_active_link(self.paths, "blue")
        self.addCleanup(self._tmp.cleanup)

    def make(self, *, runner=None, prober=None, **kw) -> Deployer:
        self.runner = runner if runner is not None else FakeRunner(self.world, self.paths)
        self.prober = prober if prober is not None else FakeProber(self.world)
        opts = dict(
            readiness_timeout=0.3,
            readiness_interval=0.02,
            drain_grace=0.0,
            stop_timeout=0.2,
            log=lambda *a, **k: None,
        )
        opts.update(kw)
        self.deployer = Deployer(paths=self.paths, runner=self.runner, prober=self.prober, **opts)
        return self.deployer

    def run_with_monitor(self, deployer) -> dict:
        with TrafficMonitor(self.world):
            result = deployer.deploy()
        return result

    def assert_no_dead_active_upstream(self) -> None:
        self.assertGreater(self.world.samples, 0, "traffic probe 必须真的采样过")
        self.assertEqual(
            self.world.violations,
            [],
            f"出现 active upstream 指向无 live ready generation 的窗口: {self.world.violations[:3]}",
        )


class Regression502Tests(Regression502Case):
    def test_successful_deploy_never_has_dead_active_upstream(self) -> None:
        d = self.make()
        result = self.run_with_monitor(d)
        self.assertTrue(result["ok"], result)
        self.assert_no_dead_active_upstream()

    def test_pre_switch_failure_never_has_dead_active_upstream(self) -> None:
        for kwargs, _reason in (
            ({"build_code": 1}, "build"),
            ({"start_code": 1}, "start"),
            ({"validate_code": 1}, "nginx-validation"),
            ({"reload_code": 1}, "switch"),
        ):
            with self.subTest(**kwargs):
                self.setUp()
                d = self.make(runner=FakeRunner(self.world, self.paths, **kwargs))
                result = self.run_with_monitor(d)
                self.assertFalse(result["ok"])
                self.assertEqual(result["stage"], "pre-switch")
                self.assert_no_dead_active_upstream()

    def test_never_ready_new_generation_never_has_dead_active_upstream(self) -> None:
        self.world.never_ready["green"] = True
        d = self.make()
        result = self.run_with_monitor(d)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "readiness")
        self.assert_no_dead_active_upstream()

    def test_post_switch_failure_never_has_dead_active_upstream(self) -> None:
        self.world.version = "9.9.9"
        d = self.make()
        result = self.run_with_monitor(d)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "post-switch-rollback")
        self.assert_no_dead_active_upstream()

    def test_probe_detects_legacy_stop_then_start_pattern(self) -> None:
        """旧行为(被 E8 封住的缺陷)在同一采样器下必须被判为 violation。"""
        runner = FakeRunner(self.world, self.paths)
        with TrafficMonitor(self.world):
            legacy_restart_sequence(self.world, runner, self.paths)
        self.assertGreater(self.world.samples, 0)
        self.assertGreater(
            len(self.world.violations),
            0,
            "采样器抓不到旧缺陷 → 这个回归测试没有鉴别力",
        )

    def test_violation_predicate_semantics(self) -> None:
        """判定点本身: active target 上没有 live+ready 的代 = violation。"""
        self.assertFalse(self.world.sample(), "旧代 live+ready 时不该报")

        self.world.delete("blue")
        self.assertTrue(self.world.sample(), "旧代已停且流量仍指向它 = violation")

        self.world.start("green")
        self.world.set_active("green")
        self.assertFalse(self.world.sample(), "新代 live+ready 且流量已切过去 = 正常")

        self.world.never_ready["green"] = True
        self.assertTrue(self.world.sample(), "新代 live 但未 ready = violation")

    def test_old_generation_stays_up_until_new_generation_is_ready(self) -> None:
        self.world.ready_delay["green"] = 0.15
        d = self.make()
        with TrafficMonitor(self.world):
            result = d.deploy()
        self.assertTrue(result["ok"], result)
        self.assert_no_dead_active_upstream()
        self.assertTrue(self.world.is_ready("green"))
        self.assertFalse(self.world.is_running("blue"))

    def test_no_moment_with_zero_generations_serving(self) -> None:
        d = self.make()
        with TrafficMonitor(self.world):
            d.deploy()
        for violation in self.world.violations:
            running = violation["running"]
            self.assertTrue(
                running.get("blue") or running.get("green"),
                f"两代同时不在: {violation}",
            )
        self.assertFalse(self.world.violations)


if __name__ == "__main__":
    unittest.main()
