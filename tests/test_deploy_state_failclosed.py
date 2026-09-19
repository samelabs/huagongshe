"""E8/B3: generation state 必须 fail-closed。

规则:
  PRE-BOOTSTRAP(site 仍是固定 8000/3001, 无 generation include) → 现网 = blue,
    install-nginx 可以初始化 active=blue;
  BOOTSTRAPPED(site 已含 generation include) → active.conf 必须存在且指向 blue.conf / green.conf,
    缺失 / 坏链 / 未知 target = DeployError —— 部署绝不把 None 猜成 blue;
  install-nginx 重跑: 已有合法 active 必须保留(不得无条件重置成 blue), 无变化时真正幂等。
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

from ops.deploy import (  # noqa: E402
    ACTIVE_LINK,
    DEFAULT_GENERATION,
    DeployError,
    Deployer,
)
from tests.deploy_fakes import (  # noqa: E402
    FakeProber,
    FakeRunner,
    FakeWorld,
    make_env,
    write_active_link,
)


class StateCase(unittest.TestCase):
    """公共夹具: 隔离临时环境。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def env(self, *, bootstrapped: bool = True):
        self.paths = make_env(self.tmp, bootstrapped=bootstrapped)
        self.world = FakeWorld()
        self.world.start(DEFAULT_GENERATION)
        return self.paths

    def deployer(self, **kw) -> Deployer:
        self.runner = FakeRunner(self.world, self.paths)
        self.prober = FakeProber(self.world)
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

    # -- 断言工具 ---------------------------------------------------------- #
    def active_link_target(self) -> str:
        return os.readlink(self.paths.nginx_gen_dir / ACTIVE_LINK)

    def assert_no_service_commands(self) -> None:
        bad = [a for a in self.runner.argv_log if a[0] != "install"]
        self.assertEqual(bad, [], f"不应触达 nginx / pm2 / npm: {bad}")

    def assert_nothing_deleted(self) -> None:
        for argv in self.runner.argv_log:
            self.assertNotEqual(argv[:2], [str(self.paths.pm2_bin), "delete"])


class PreBootstrapTests(StateCase):
    def test_install_initializes_blue_when_site_is_pre_bootstrap(self) -> None:
        p = self.env(bootstrapped=False)
        d = self.deployer()
        self.assertFalse(d.site_bootstrapped())
        self.assertIsNone(d.active_generation())

        result = d.install_nginx()

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["changed"])
        self.assertEqual(result["active"], DEFAULT_GENERATION)
        self.assertTrue(result["link_changed"])
        self.assertEqual(self.active_link_target(), f"{DEFAULT_GENERATION}.conf")
        site = p.nginx_site_conf.read_text(encoding="utf-8")
        self.assertIn(str(p.nginx_gen_dir / ACTIVE_LINK), site)
        self.assertIn("http://hgs_api_active;", site)
        self.assertIn("http://hgs_web_active;", site)
        self.assertNotIn("127.0.0.1:8000;", site)
        flat = [" ".join(a) for a in self.runner.argv_log]
        i_check = next(i for i, a in enumerate(flat) if a.endswith(" -t"))
        i_reload = next(i for i, a in enumerate(flat) if "reload" in a)
        self.assertLess(i_check, i_reload, "必须先 nginx -t 再 reload")

    def test_pre_bootstrap_deploy_assumes_blue_without_running_anything(self) -> None:
        self.env(bootstrapped=False)
        d = self.deployer()

        self.assertEqual(d.require_active(), DEFAULT_GENERATION)
        self.assertIn("active.assumed", d.event_names())
        self.assertEqual(self.runner.argv_log, [], "判定阶段不得执行命令")


class BootstrappedPreserveTests(StateCase):
    def test_bootstrapped_blue_is_preserved_and_idempotent(self) -> None:
        p = self.env()
        write_active_link(p, "blue")
        d = self.deployer()
        self.assertTrue(d.site_bootstrapped())
        before_site = p.nginx_site_conf.read_text(encoding="utf-8")

        result = d.install_nginx()

        self.assertEqual(result["active"], "blue")
        self.assertFalse(result["changed"])
        self.assertFalse(result["link_changed"])
        self.assertEqual(self.active_link_target(), "blue.conf")
        self.assertEqual(p.nginx_site_conf.read_text(encoding="utf-8"), before_site)
        self.assertIn("install.active_link.preserved", d.event_names())
        self.assert_no_service_commands()
        # include 只出现一次: 重复运行不得嵌套 include / 重复 rewrite
        self.assertEqual(
            p.nginx_site_conf.read_text(encoding="utf-8").count(str(p.nginx_gen_dir / ACTIVE_LINK)), 1
        )
        self.assertEqual(p.nginx_site_conf.read_text(encoding="utf-8").count("http://hgs_api_active;"), 1)

    def test_bootstrapped_green_is_preserved_not_reset_to_blue(self) -> None:
        p = self.env()
        write_active_link(p, "green")
        d = self.deployer()

        result = d.install_nginx()

        self.assertEqual(result["active"], "green")
        self.assertEqual(self.active_link_target(), "green.conf")
        self.assertIn("install.active_link.preserved", d.event_names())
        self.assertEqual(
            [e for n, e in d.events if n == "install.active_link.initialized"],
            [],
            "已有合法 active 时不得重新初始化成 blue",
        )

    def test_install_is_idempotent_after_first_bootstrap(self) -> None:
        p = self.env(bootstrapped=False)
        d = self.deployer()

        first = d.install_nginx()
        second = d.install_nginx()

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertFalse(second["link_changed"])
        self.assertEqual(self.active_link_target(), "blue.conf")
        self.assertEqual(
            p.nginx_site_conf.read_text(encoding="utf-8").count(str(p.nginx_gen_dir / ACTIVE_LINK)), 1
        )
        self.assertEqual(
            p.nginx_site_conf.read_text(encoding="utf-8").count("http://hgs_api_active;"), 1
        )

    def test_install_repairs_dangling_active_link(self) -> None:
        p = self.env()
        (p.nginx_gen_dir / "green.conf").unlink()
        os.symlink("green.conf", p.nginx_gen_dir / ACTIVE_LINK)  # 坏链: 目标文件不存在
        d = self.deployer()
        self.assertIsNone(d.active_generation())

        result = d.install_nginx()

        self.assertEqual(result["active"], DEFAULT_GENERATION)
        self.assertEqual(self.active_link_target(), f"{DEFAULT_GENERATION}.conf")
        self.assertIn("install.active_link.initialized", d.event_names())


class FailClosedTests(StateCase):
    def test_missing_active_conf_fails_closed(self) -> None:
        self.env()  # bootstrapped, 但没有 active.conf
        d = self.deployer()
        self.assertTrue(d.site_bootstrapped())
        self.assertIsNone(d.active_generation())

        with self.assertRaises(DeployError) as ctx:
            d.deploy()

        self.assertIn(ACTIVE_LINK, str(ctx.exception))
        self.assertEqual(self.runner.argv_log, [], "fail-closed 阶段不得执行任何命令")
        self.assertNotIn("active.assumed", d.event_names(), "bootstrapped 状态下不得猜 blue")
        self.assertEqual(self.world.active, "blue")
        self.assert_nothing_deleted()

    def test_unknown_active_target_fails_closed(self) -> None:
        p = self.env()
        os.symlink("purple.conf", p.nginx_gen_dir / ACTIVE_LINK)
        d = self.deployer()
        self.assertIsNone(d.active_generation())

        with self.assertRaises(DeployError):
            d.require_active()
        with self.assertRaises(DeployError):
            d.deploy()

        self.assertEqual(self.runner.argv_log, [])
        self.assert_nothing_deleted()

    def test_dangling_active_link_fails_closed(self) -> None:
        p = self.env()
        (p.nginx_gen_dir / "green.conf").unlink()
        os.symlink("green.conf", p.nginx_gen_dir / ACTIVE_LINK)
        d = self.deployer()
        self.assertIsNone(d.active_generation())

        with self.assertRaises(DeployError):
            d.deploy()

        self.assertEqual(self.runner.argv_log, [])
        self.assert_nothing_deleted()

    def test_unreadable_site_config_fails_closed(self) -> None:
        self.env()
        self.paths.nginx_site_conf.unlink()
        d = self.deployer()

        with self.assertRaises(DeployError):
            d.deploy()

        self.assertEqual(self.runner.argv_log, [])

    def test_regular_file_active_is_not_a_valid_generation(self) -> None:
        p = self.env()
        (p.nginx_gen_dir / ACTIVE_LINK).write_text("blue\n", encoding="utf-8")  # 不是 symlink
        d = self.deployer()
        self.assertIsNone(d.active_generation())

        with self.assertRaises(DeployError):
            d.deploy()

        self.assertEqual(self.runner.argv_log, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
