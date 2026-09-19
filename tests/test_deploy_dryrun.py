"""E8/B4: `--dry-run` 必须真正无副作用。

允许: read / 内存渲染 / 静态校验 / 计划输出。
禁止: npm build、PM2 mutation、nginx mutation 或 reload、symlink 与 site config 写入、
      生产 `.next` 改动。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.deploy import ACTIVE_LINK, _build_parser  # noqa: E402
from tests.deploy_fakes import (  # noqa: E402
    FakeProber,
    FakeRunner,
    FakeWorld,
    make_env,
    snapshot,
    write_active_link,
)


class DryRunCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.paths = make_env(self.tmp)
        self.world = FakeWorld()
        self.world.start("blue")
        write_active_link(self.paths, "blue")

    def deployer(self, *, runner=None, prober=None, **kw):
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
        self.d = Deployer(paths=self.paths, runner=self.runner, prober=self.prober, **opts)
        return self.d


from ops.deploy import Deployer  # noqa: E402  (放这里以保持 import 分组清晰)


class DryRunTests(DryRunCase):
    def test_dry_run_never_runs_the_build_runner(self) -> None:
        d = self.deployer(dry_run=True)
        before_tree = snapshot(self.tmp)

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual(self.runner.argv_log, [], "dry-run 不得执行任何命令")
        self.assertEqual(self.runner.builds, [], "build runner 不得收到 npm run build")
        self.assertEqual(self.runner.env_log, [])
        self.assertNotIn("build.begin", d.event_names())
        self.assertIn("build.skipped", d.event_names())
        self.assertEqual(snapshot(self.tmp), before_tree, "dry-run 不得改动任何文件/symlink")

    def test_dry_run_does_not_touch_production_next_artifacts(self) -> None:
        web = self.paths.web_dir
        (web / ".next-blue").mkdir(parents=True, exist_ok=True)
        (web / ".next-blue" / "BUILD_ID").write_text("blue\n", encoding="utf-8")
        d = self.deployer(dry_run=True)

        d.deploy()

        self.assertEqual((web / ".next-blue" / "BUILD_ID").read_text(encoding="utf-8"), "blue\n")
        self.assertFalse((web / ".next-green").exists())
        self.assertFalse((web / ".next").exists())

    def test_control_non_dry_run_does_invoke_build(self) -> None:
        d = self.deployer()

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual([b["dist"] for b in self.runner.builds], [".next-green"])
        self.assertIn("build.begin", d.event_names())

    def test_dry_run_is_side_effect_free_even_when_every_stage_would_fail(self) -> None:
        self.world.version = "9.9.9"
        runner = FakeRunner(
            self.world,
            self.paths,
            build_code=1,
            start_code=1,
            validate_code=1,
            reload_code=1,
            pgrep_code=127,
        )
        d = self.deployer(runner=runner, dry_run=True)
        before_tree = snapshot(self.tmp)

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual(runner.argv_log, [])
        self.assertEqual(snapshot(self.tmp), before_tree)

    def test_dry_run_mutates_no_symlink_no_service_no_spec_file(self) -> None:
        d = self.deployer(dry_run=True)
        before_link = os.readlink(self.paths.nginx_gen_dir / ACTIVE_LINK)

        d.deploy()

        self.assertEqual(os.readlink(self.paths.nginx_gen_dir / ACTIVE_LINK), before_link)
        self.assertEqual(self.world.active, "blue")
        self.assertFalse(self.world.is_running("green"))
        self.assertFalse((self.paths.state_dir / "ecosystem-green.cjs").exists())
        self.assertEqual(
            [a for a in self.runner.argv_log if a[0] in ("pm2", "nginx", "npm")],
            [],
            "dry-run 不得触达 pm2 / nginx / npm",
        )

    def test_dry_run_install_nginx_writes_nothing(self) -> None:
        # 独立临时目录: "没有 active.conf" 必须是环境本身的状态, 而不是被 setUp 写出来的
        with tempfile.TemporaryDirectory() as td:
            fresh = Path(td)
            self.paths = make_env(fresh, bootstrapped=False)
            self.world = FakeWorld()
            self.world.start("blue")
            d = self.deployer(dry_run=True)
            before_tree = snapshot(fresh)

            result = d.install_nginx()

            self.assertTrue(result["ok"], result)
            self.assertEqual(self.runner.argv_log, [])
            self.assertEqual(snapshot(fresh), before_tree)
            link = self.paths.nginx_gen_dir / ACTIVE_LINK
            self.assertFalse(link.exists() or link.is_symlink())

    def test_cli_parser_exposes_dry_run_and_reload_timeout(self) -> None:
        args = _build_parser().parse_args(["--dry-run", "--json", "--reload-timeout", "3"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.reload_timeout, 3.0)
        self.assertEqual(_build_parser().parse_args([]).reload_timeout, 10.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
