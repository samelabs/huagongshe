"""E8 部署编排故障/顺序测试 —— 不触碰真实 nginx / PM2 / 生产端口。

覆盖 §9 的编排故障面: 新代启动成功/失败、永不 ready、worker 未上线、nginx 校验失败、
traffic switch 失败、post-switch smoke 失败、rollback 回到旧代、旧代不得早于 switch+smoke
退出、成功部署最终停掉旧代; 另加 §8 的"部署计划里不得有 migration"证据断言。
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

from ops.deploy import (  # noqa: E402
    GENERATIONS,
    DeployError,
    Deployer,
    render_spec_text,
    spec_substitutions,
)
from tests.deploy_fakes import (  # noqa: E402
    FakeProber,
    FakeRunner,
    FakeWorld,
    make_env,
    snapshot,
    write_active_link,
)

FORBIDDEN_PLAN_TOKENS = ("migrate", "psql", "alembic", "createdb", "schema_migrations")


class DeployCase(unittest.TestCase):
    """公共夹具: 隔离临时环境 + 已在服务的旧代 blue。"""

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

    # -- 断言工具 ---------------------------------------------------------- #
    def flat_argv(self) -> list[str]:
        return [" ".join(a) for a in self.runner.argv_log]

    def assert_old_generation_never_stopped(self, gen: str = "blue") -> None:
        apps = set(GENERATIONS[gen].apps())
        for argv in self.runner.argv_log:
            if argv[:2] == [str(self.paths.pm2_bin), "delete"]:
                self.assertFalse(set(argv[2:]) & apps, f"旧代 {gen} 被误停: {' '.join(argv)}")

    def assert_no_traffic_switch(self) -> None:
        self.assertNotIn("switch.ok", self.deployer.event_names())
        for argv in self.runner.argv_log:
            self.assertNotIn("reload", argv, f"不应 reload nginx: {' '.join(argv)}")


class SuccessPathTests(DeployCase):
    def test_successful_deploy_starts_new_switches_traffic_then_stops_old(self) -> None:
        d = self.make()
        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stage"], "success")
        self.assertEqual(result["active"], "green")
        self.assertEqual(result["stopped"], "blue")
        self.assertTrue(self.world.is_running("green"))
        self.assertFalse(self.world.is_running("blue"), "旧代必须被停掉")
        self.assertEqual(d.active_generation(), "green")

        names = d.event_names()
        self.assertLess(names.index("switch.ok"), names.index("drain.stopped"))
        self.assertLess(names.index("smoke.ok"), names.index("drain.begin"))
        self.assertLess(names.index("start.ok"), names.index("switch.begin"))

    def test_new_generation_is_deleted_before_start_for_clean_env(self) -> None:
        d = self.make()
        d.deploy()
        flat = self.flat_argv()
        delete_idx = next(i for i, c in enumerate(flat) if c.startswith("pm2 delete huagongshe-api-green"))
        start_idx = next(i for i, c in enumerate(flat) if "pm2 start" in c and "green" in c)
        self.assertLess(delete_idx, start_idx)

    def test_old_generation_apps_are_deleted_only_after_success(self) -> None:
        d = self.make()
        d.deploy()
        flat = self.flat_argv()
        old_delete = [c for c in flat if c.startswith("pm2 delete huagongshe-api huagongshe")]
        self.assertEqual(len(old_delete), 1, flat)

    def test_deploy_plan_has_no_migration_or_schema_step(self) -> None:
        d = self.make()
        d.deploy()
        for cmd in self.flat_argv():
            for token in FORBIDDEN_PLAN_TOKENS:
                self.assertNotIn(token, cmd, f"部署计划出现 migration 类步骤: {cmd}")

    def test_status_is_read_only(self) -> None:
        d = self.make()
        status = d.status()
        self.assertEqual(status["active"], "blue")
        self.assertEqual(self.runner.argv_log, [], "status 不得执行任何命令")


class PreSwitchFailureTests(DeployCase):
    def test_build_failure_starts_nothing(self) -> None:
        d = self.make(runner=FakeRunner(self.world, self.paths, build_code=1))
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "pre-switch")
        self.assertEqual(result["reason"], "build")
        self.assertFalse(self.world.is_running("green"))
        self.assertTrue(self.world.is_running("blue"))
        self.assertNotIn("start.ok", d.event_names())
        self.assert_no_traffic_switch()
        self.assert_old_generation_never_stopped()

    def test_new_generation_start_failure_keeps_old_serving(self) -> None:
        d = self.make(runner=FakeRunner(self.world, self.paths, start_code=1))
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "start")
        self.assertEqual(result["active"], "blue")
        self.assertFalse(result["traffic_switched"])
        self.assertTrue(self.world.is_running("blue"))
        self.assert_no_traffic_switch()
        self.assert_old_generation_never_stopped()

    def test_new_generation_never_ready_is_bounded_and_keeps_old(self) -> None:
        self.world.never_ready["green"] = True
        d = self.make()
        started = time.monotonic()
        result = d.deploy()
        elapsed = time.monotonic() - started

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "readiness")
        self.assertLess(elapsed, 5.0, "readiness 等待必须有界")
        self.assertTrue(self.world.is_running("blue"))
        self.assertFalse(self.world.is_running("green"), "失败的新代必须被清理")
        self.assertIn("ready.timeout", d.event_names())
        self.assert_no_traffic_switch()
        self.assert_old_generation_never_stopped()

    def test_new_generation_worker_not_online_blocks_switch(self) -> None:
        self.world.worker_start_fail["green"] = True
        d = self.make()
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "worker")
        self.assertTrue(self.world.is_running("blue"))
        self.assert_no_traffic_switch()
        self.assert_old_generation_never_stopped()

    def test_nginx_validation_failure_leaves_old_upstream_untouched(self) -> None:
        d = self.make(runner=FakeRunner(self.world, self.paths, validate_code=1))
        before = self.paths.nginx_site_conf.read_text(encoding="utf-8")
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "nginx-validation")
        self.assertEqual(self.paths.nginx_site_conf.read_text(encoding="utf-8"), before)
        self.assertEqual(d.active_generation(), "blue", "校验失败不得改 active upstream")
        self.assertFalse(self.world.is_running("green"))
        self.assert_no_traffic_switch()
        self.assert_old_generation_never_stopped()

    def test_traffic_switch_failure_restores_old_upstream(self) -> None:
        d = self.make(runner=FakeRunner(self.world, self.paths, reload_code=1))
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "switch")
        self.assertIn("switch.failed", d.event_names())
        self.assertIn("switch.restored", d.event_names())
        self.assertEqual(d.active_generation(), "blue", "reload 失败后 symlink 必须回到旧代")
        self.assertTrue(self.world.is_running("blue"))
        self.assertFalse(self.world.is_running("green"))
        self.assert_old_generation_never_stopped()

    def test_target_equal_to_active_is_refused(self) -> None:
        d = self.make()
        with self.assertRaises(DeployError):
            d.deploy(target="blue")
        self.assertEqual(self.runner.argv_log, [], "防呆拒绝不得产生任何命令")


class PostSwitchRollbackTests(DeployCase):
    def test_post_switch_smoke_failure_rolls_back_to_old(self) -> None:
        self.world.version = "9.9.9"  # MCP serverInfo 与 VERSION 不符 → smoke 失败
        d = self.make()
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "post-switch-rollback")
        self.assertEqual(result["reason"], "smoke")
        self.assertEqual(result["active"], "blue")
        self.assertTrue(result["old_verified"], "rollback 后必须验证旧代")
        self.assertEqual(d.active_generation(), "blue")
        self.assertTrue(self.world.is_running("blue"))
        self.assertFalse(self.world.is_running("green"))
        self.assert_old_generation_never_stopped()

    def test_post_switch_page_failure_rolls_back_to_old(self) -> None:
        d = self.make(prober=FakeProber(self.world, page_status=500))
        result = d.deploy()

        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "post-switch-rollback")
        self.assertEqual(d.active_generation(), "blue")
        self.assertTrue(self.world.is_running("blue"))
        self.assert_old_generation_never_stopped()

    def test_rollback_happens_before_new_generation_is_stopped(self) -> None:
        self.world.version = "9.9.9"
        d = self.make()
        d.deploy()
        names = d.event_names()
        self.assertLess(names.index("rollback.begin"), names.index("rollback.done"))
        self.assertLess(names.index("rollback.begin"), names.index("cleanup.done"))

    def test_old_generation_still_serving_when_new_generation_fails_post_switch(self) -> None:
        self.world.version = "9.9.9"
        d = self.make()
        d.deploy()
        self.assertTrue(self.world.is_ready("blue"))
        self.assertEqual(d.active_generation(), "blue")


class SpecRenderingTests(DeployCase):
    def test_generation_specs_match_canonical_ecosystem(self) -> None:
        canonical = (REPO_ROOT / "ecosystem.config.cjs").read_text(encoding="utf-8")
        blue = render_spec_text(GENERATIONS["blue"], canonical, self.paths)
        green = render_spec_text(GENERATIONS["green"], canonical, self.paths)

        # blue = 现网 canonical 定义(名字/端口不变)
        for literal in (
            'name: "huagongshe-api",',
            'name: "huagongshe",',
            'name: "huagongshe-pubchem-worker",',
            "--port 8000 ",
            'next start -H 127.0.0.1 -p 3001"',
            'HGS_WORKAPI_URL: "http://127.0.0.1:8000"',
        ):
            self.assertIn(literal, blue, literal)

        # green = 同一定义换 generation 端口/名字 + 显式 API origin + 独立 worker id
        for literal in (
            'name: "huagongshe-api-green",',
            'name: "huagongshe-green",',
            'name: "huagongshe-pubchem-worker-green",',
            "--port 8010 ",
            'next start -H 127.0.0.1 -p 3011"',
            'HGS_WORKAPI_URL: "http://127.0.0.1:8010"',
            'API_ORIGIN_INTERNAL: "http://127.0.0.1:8010"',
            'HGS_WORKER_ID: "server-local-1-green"',
        ):
            self.assertIn(literal, green, literal)

        # 有界 graceful stop: 三个 app 都拿到 kill_timeout
        self.assertEqual(blue.count("kill_timeout: 10000,"), 3)
        self.assertEqual(green.count("kill_timeout: 10000,"), 3)

    def test_spec_rendering_fails_closed_when_ecosystem_drifts(self) -> None:
        canonical = (REPO_ROOT / "ecosystem.config.cjs").read_text(encoding="utf-8")
        broken = canonical.replace("--port 8000 ", "--port 9000 ")
        with self.assertRaises(DeployError):
            render_spec_text(GENERATIONS["green"], broken, self.paths)

    def test_spec_rendering_fails_closed_on_missing_app_name_anchor(self) -> None:
        canonical = (REPO_ROOT / "ecosystem.config.cjs").read_text(encoding="utf-8")
        broken = canonical.replace('name: "huagongshe-pubchem-worker",', 'name: "worker",')
        with self.assertRaises(DeployError):
            render_spec_text(GENERATIONS["green"], broken, self.paths)

    def test_substitutions_are_narrow(self) -> None:
        subs = spec_substitutions(GENERATIONS["green"], self.paths)
        self.assertTrue(subs)
        for anchor, replacement, count in subs:
            self.assertIsInstance(anchor, str)
            self.assertIsInstance(replacement, str)
            self.assertGreaterEqual(count, 1)


class DryRunTests(DeployCase):
    def test_dry_run_touches_no_files_and_no_services(self) -> None:
        d = self.make(dry_run=True)  # 不 skip_build: dry-run 自己也不许 build(B4)
        before_site = self.paths.nginx_site_conf.read_text(encoding="utf-8")
        before_tree = snapshot(self.tmp)
        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual(self.runner.argv_log, [], "dry-run 不得执行命令")
        self.assertEqual(self.paths.nginx_site_conf.read_text(encoding="utf-8"), before_site)
        self.assertEqual(snapshot(self.tmp), before_tree, "dry-run 不得改动任何文件/symlink")
        self.assertFalse((self.paths.state_dir / "ecosystem-green.cjs").exists())
        self.assertFalse((self.paths.web_dir / ".next-green").exists())
