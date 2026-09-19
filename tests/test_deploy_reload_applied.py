"""E8/B2: `nginx -s reload` exit 0 不等于"新配置已生效"。

判定 = reload 信号成功 **且** 观察到 reload 前不存在的 nginx worker PID(master 仍存活);
旧 worker 允许仍在 graceful drain。只有 applied 之后才允许 verify traffic → smoke → 停旧代;
rollback 也必须"恢复 symlink + 再次 reload + 等到 applied", 否则 stage = rollback-failed。
"""

from __future__ import annotations

import sys
import tempfile
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
    make_env,
    write_active_link,
)


class ReloadAppliedCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.paths = make_env(self.tmp)
        self.world = FakeWorld()
        self.world.start("blue")
        write_active_link(self.paths, "blue")

    def deployer(self, *, runner=None, prober=None, **kw) -> Deployer:
        self.runner = runner if runner is not None else FakeRunner(self.world, self.paths)
        self.prober = prober if prober is not None else FakeProber(self.world)
        opts = dict(
            readiness_timeout=0.3,
            readiness_interval=0.02,
            drain_grace=0.0,
            stop_timeout=0.2,
            reload_timeout=0.2,
            log=lambda *a, **k: None,
        )
        opts.update(kw)
        self.d = Deployer(paths=self.paths, runner=self.runner, prober=self.prober, **opts)
        return self.d

    # -- 断言工具 ---------------------------------------------------------- #
    def reload_commands(self) -> list[list[str]]:
        return [a for a in self.runner.argv_log if "reload" in a]

    def assert_old_generation_never_stopped(self, gen: str = "blue") -> None:
        apps = set(GENERATIONS[gen].apps())
        for argv in self.runner.argv_log:
            if argv[:2] == [str(self.paths.pm2_bin), "delete"]:
                self.assertFalse(set(argv[2:]) & apps, f"旧代 {gen} 被误停: {' '.join(argv)}")

    def applied_payload(self) -> dict:
        return [e for n, e in self.d.events if n == "switch.applied"][0]


class AppliedDetectionTests(ReloadAppliedCase):
    def test_successful_worker_rotation_marks_switch_applied(self) -> None:
        d = self.deployer()

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        names = d.event_names()
        self.assertIn("switch.applied", names)
        self.assertLess(names.index("switch.applied"), names.index("smoke.ok"))
        self.assertLess(names.index("switch.applied"), names.index("drain.begin"))
        payload = self.applied_payload()
        self.assertTrue(payload["new_workers"], "applied 必须带新 worker 证据")
        self.assertTrue(
            set(payload["new_workers"]).isdisjoint({5001, 5002}),
            "applied 必须来自 reload 之后新出现的 worker PID",
        )
        self.assertEqual(self.world.reload_applied, 1)

    def test_reload_exit_zero_without_new_worker_is_switch_failure(self) -> None:
        self.world.reload_applies = False  # 信号成功, 但配置没生效(worker 不轮换)
        d = self.deployer()

        result = d.deploy()

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "pre-switch")
        self.assertEqual(result["reason"], "switch")
        names = d.event_names()
        self.assertIn("reload.not_applied", names)
        self.assertNotIn("switch.applied", names)
        self.assertNotIn("switch.ok", names)
        self.assertNotIn("smoke.ok", names)
        self.assertEqual(self.world.active, "blue", "运行中的 nginx 仍服务旧代")
        self.assertEqual(d.active_generation(), "blue", "磁盘 symlink 与运行状态一致")
        self.assert_old_generation_never_stopped()
        self.assertFalse(self.world.is_running("green"), "失败的新代必须被清理")
        self.assertTrue(self.world.is_running("blue"))

    def test_master_gone_is_switch_failure(self) -> None:
        self.world.nginx_master_alive = False
        d = self.deployer()

        result = d.deploy()

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "switch")
        self.assertIn("reload.master_gone", d.event_names())
        self.assertNotIn("switch.applied", d.event_names())
        self.assert_old_generation_never_stopped()

    def test_probe_unavailable_fails_closed_before_touching_nginx(self) -> None:
        runner = FakeRunner(self.world, self.paths, pgrep_code=127)
        d = self.deployer(runner=runner)

        result = d.deploy()

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "switch")
        self.assertIn("nginx.probe.unavailable", d.event_names())
        self.assertNotIn("switch.applied", d.event_names())
        self.assertEqual(self.reload_commands(), [], "拿不到 worker 视图时不得发 reload 信号")
        self.assert_old_generation_never_stopped()


class RollbackReloadTests(ReloadAppliedCase):
    def test_rollback_restores_link_and_performs_second_reload(self) -> None:
        self.world.version = "9.9.9"  # post-switch smoke 失败
        d = self.deployer()

        result = d.deploy()

        self.assertEqual(result["stage"], "post-switch-rollback")
        self.assertTrue(result["old_verified"])
        self.assertEqual(d.active_generation(), "blue")
        self.assertEqual(self.world.active, "blue")
        self.assertEqual(self.world.reload_attempts, 2, "switch 一次 + rollback 一次")
        self.assertEqual(self.world.reload_applied, 2)
        self.assertEqual(len(self.reload_commands()), 2)
        self.assertIn("rollback.done", d.event_names())
        self.assertTrue(self.world.is_running("blue"))
        self.assertFalse(self.world.is_running("green"), "失败的新代在旧代验证通过后清理")

    def test_rollback_reload_not_applied_reports_rollback_failed(self) -> None:
        self.world.version = "9.9.9"  # smoke 失败
        self.world.reload_applies_sequence = [True, False]  # switch 生效; rollback reload 不生效
        d = self.deployer()

        result = d.deploy()

        self.assertEqual(result["stage"], "rollback-failed")
        self.assertFalse(result["old_verified"], "不得谎报旧代已恢复")
        self.assertEqual(result["active"], "green")
        self.assertEqual(d.active_generation(), "green", "磁盘 symlink 必须与运行中的 nginx 一致")
        self.assertEqual(self.world.active, "green")
        self.assertIn("rollback.failed", d.event_names())
        self.assertNotIn("rollback.done", d.event_names())
        self.assertTrue(self.world.is_running("green"), "仍在服务的新代不得被清理")
        self.assertTrue(self.world.is_running("blue"))

    def test_old_generation_survives_when_smoke_fails_after_applied_switch(self) -> None:
        self.world.version = "9.9.9"
        d = self.deployer()

        result = d.deploy()

        self.assertFalse(result["ok"], result)
        self.assertIn("switch.applied", d.event_names())
        self.assertNotIn("smoke.ok", d.event_names())
        self.assert_old_generation_never_stopped()
        self.assertTrue(self.world.is_running("blue"))

    def test_old_generation_deleted_only_after_applied_and_smoke_ok(self) -> None:
        d = self.deployer()

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        names = d.event_names()
        self.assertLess(names.index("switch.applied"), names.index("drain.begin"))
        self.assertLess(names.index("smoke.ok"), names.index("drain.begin"))
        deleted = [a for a in self.runner.argv_log if a[:2] == [str(self.paths.pm2_bin), "delete"]]
        self.assertTrue(
            any(set(a[2:]) & set(GENERATIONS["blue"].apps()) for a in deleted),
            "成功路径最终必须停掉旧代",
        )
        self.assertFalse(self.world.is_running("blue"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
