"""E8 nginx traffic-switch 测试 —— 候选校验/原子 symlink 替换/一次性迁移(install-nginx)。

全程使用临时 config 树与假命令, 不读不写真实 /etc/nginx, 不 reload 真实 nginx。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.deploy import (  # noqa: E402
    ACTIVE_LINK,
    GENERATIONS,
    DeployError,
    Deployer,
    Paths,
)
from tests.deploy_fakes import (  # noqa: E402
    SITE_CONF_FIXTURE,
    FakeProber,
    FakeRunner,
    FakeWorld,
    make_env,
    write_active_link,
)


class SnapshotRunner(FakeRunner):
    """在 `nginx -t` 被调用的瞬间把候选 config 树内容抓下来(用于断言候选真被验证)。"""

    def __init__(self, world, paths, **kw) -> None:
        super().__init__(world, paths, **kw)
        self.validated_main: str | None = None
        self.validated_site: str | None = None

    def run(self, argv, *, cwd=None, timeout: float = 300.0, env=None):
        a = [str(x) for x in argv]
        if "nginx" in a and "-t" in a and "-c" in a:
            main = Path(a[a.index("-c") + 1])
            self.validated_main = main.read_text(encoding="utf-8") if main.exists() else None
            sites = sorted((main.parent / "sites").glob("*")) if (main.parent / "sites").is_dir() else []
            if sites:
                self.validated_site = sites[0].read_text(encoding="utf-8")
        return super().run(argv, cwd=cwd, timeout=timeout, env=env)


class NginxCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def env(self, **kw) -> Paths:
        self.paths = make_env(self.tmp, **kw)
        return self.paths

    def make(self, *, runner=None, prober=None, paths=None, **kw) -> Deployer:
        paths = paths or self.paths
        self.world = FakeWorld()
        self.world.start("blue")
        write_active_link(paths, "blue")
        self.runner = runner if runner is not None else FakeRunner(self.world, paths)
        self.prober = prober if prober is not None else FakeProber(self.world)
        opts = dict(
            readiness_timeout=0.2,
            readiness_interval=0.02,
            drain_grace=0.0,
            stop_timeout=0.1,
            log=lambda *a, **k: None,
        )
        opts.update(kw)
        self.deployer = Deployer(paths=paths, runner=self.runner, prober=self.prober, **opts)
        return self.deployer

    def commands(self) -> list[str]:
        return [" ".join(a) for a in self.runner.argv_log]


class CandidateValidationTests(NginxCase):
    def test_candidate_is_validated_in_temp_tree_with_candidate_include(self) -> None:
        paths = self.env()
        runner = SnapshotRunner(FakeWorld(), paths)
        d = self.make(paths=paths, runner=runner)

        self.assertTrue(d.validate_candidate(GENERATIONS["green"]))

        self.assertIsNotNone(runner.validated_main, "必须用 -c 指定临时主配置")
        self.assertNotIn("error_log", runner.validated_main, "测试配置不得写线上 error_log")
        self.assertIn(str(paths.nginx_gen_dir / "green.conf"), runner.validated_site or "")
        self.assertNotIn(str(paths.nginx_gen_dir / ACTIVE_LINK), runner.validated_site or "")

        argv = [a for a in runner.argv_log if "-c" in a][0]
        tmp_conf = Path(argv[argv.index("-c") + 1])
        self.assertNotEqual(tmp_conf.parent, paths.nginx_conf.parent)
        self.assertFalse(tmp_conf.exists(), "临时 config 树必须被清理")

    def test_live_files_untouched_by_validation(self) -> None:
        paths = self.env()
        site_before = paths.nginx_site_conf.read_text(encoding="utf-8")
        d = self.make(paths=paths)
        d.validate_candidate(GENERATIONS["green"])

        self.assertEqual(paths.nginx_site_conf.read_text(encoding="utf-8"), site_before)
        self.assertEqual(d.active_generation(), "blue")

    def test_validation_failure_does_not_reload_or_switch(self) -> None:
        paths = self.env()
        runner = FakeRunner(FakeWorld(), paths, validate_code=1)
        d = self.make(paths=paths, runner=runner)

        self.assertFalse(d.validate_candidate(GENERATIONS["green"]))
        self.assertNotIn("switch.ok", d.event_names())
        for cmd in self.commands():
            self.assertNotIn("-s reload", cmd)

    def test_validate_candidate_fails_closed_when_site_config_not_bootstrapped(self) -> None:
        paths = self.env(bootstrapped=False)
        d = self.make(paths=paths)
        with self.assertRaises(DeployError):
            d.validate_candidate(GENERATIONS["green"])


class AtomicSwitchTests(NginxCase):
    def test_switch_uses_atomic_rename_and_lands_on_new_generation(self) -> None:
        paths = self.env()
        d = self.make(paths=paths)
        calls: list[tuple[str, str]] = []
        real_replace = __import__("os").replace

        def spy(src, dst):
            calls.append((str(src), str(dst)))
            return real_replace(src, dst)

        import ops.deploy as mod

        original = mod.os.replace
        mod.os.replace = spy
        try:
            self.assertTrue(d.switch_traffic(GENERATIONS["green"], previous="blue"))
        finally:
            mod.os.replace = original

        link = paths.nginx_gen_dir / ACTIVE_LINK
        self.assertEqual(len(calls), 1)
        self.assertEqual(Path(calls[0][0]).name, f"{ACTIVE_LINK}.tmp")
        self.assertEqual(Path(calls[0][1]), link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve().name, "green.conf")
        self.assertFalse((paths.nginx_gen_dir / f"{ACTIVE_LINK}.tmp").exists(), "临时 symlink 不得残留")
        self.assertEqual(d.active_generation(), "green")
        self.assertIn("-s reload", "\n".join(self.commands()))

    def test_switch_failure_restores_previous_generation_link(self) -> None:
        paths = self.env()
        runner = FakeRunner(FakeWorld(), paths, reload_code=1)
        d = self.make(paths=paths, runner=runner)

        self.assertFalse(d.switch_traffic(GENERATIONS["green"], previous="blue"))
        self.assertIn("switch.restored", d.event_names())
        link = paths.nginx_gen_dir / ACTIVE_LINK
        self.assertEqual(link.resolve().name, "blue.conf")

    def test_generation_files_carry_expected_upstream_ports(self) -> None:
        paths = self.env()
        d = self.make(paths=paths)
        blue = d.render_nginx_generation(GENERATIONS["blue"])
        green = d.render_nginx_generation(GENERATIONS["green"])

        blue_text = blue.read_text(encoding="utf-8")
        green_text = green.read_text(encoding="utf-8")
        self.assertIn("upstream hgs_api_active", blue_text)
        self.assertIn("server 127.0.0.1:8000;", blue_text)
        self.assertIn("server 127.0.0.1:3001;", blue_text)
        self.assertIn("server 127.0.0.1:8010;", green_text)
        self.assertIn("server 127.0.0.1:3011;", green_text)
        self.assertNotEqual(blue_text, green_text)


class InstallNginxTests(NginxCase):
    def test_install_migrates_site_config_then_is_idempotent(self) -> None:
        paths = self.env(bootstrapped=False)
        original = paths.nginx_site_conf.read_text(encoding="utf-8")
        d = self.make(paths=paths)

        first = d.install_nginx()
        self.assertTrue(first["changed"])
        migrated = paths.nginx_site_conf.read_text(encoding="utf-8")
        self.assertIn(f"include {paths.nginx_gen_dir / ACTIVE_LINK};", migrated)
        self.assertIn("proxy_pass http://hgs_api_active;", migrated)
        self.assertIn("proxy_pass http://hgs_web_active;", migrated)
        self.assertNotIn("127.0.0.1:3001", migrated)
        self.assertNotIn("127.0.0.1:8000", migrated)
        # 回归锁(生产事故): 备份必须在 nginx include 目录之外
        backup_dir = paths.nginx_gen_dir.parent
        backups = list(backup_dir.glob(paths.nginx_site_conf.name + ".bak-*"))
        self.assertEqual(len(backups), 1, "首次 install 有且仅有一个 backup")
        self.assertEqual(backups[0].read_text(encoding="utf-8"), original, "backup 内容 == original")
        self.assertNotEqual(backups[0].parent, paths.nginx_site_conf.parent,
                            "backup 不得位于 sites-enabled/(nginx include 目录)")
        self.assertEqual(list(paths.nginx_site_conf.parent.glob(paths.nginx_site_conf.name + ".bak-*")),
                         [], "sites-enabled/ 中不得存在 huagongshe.bak-*")
        self.assertEqual((paths.nginx_gen_dir / ACTIVE_LINK).resolve().name, "blue.conf")
        self.assertEqual(sum(1 for c in self.commands() if "-s reload" in c), 1)

        # 第二次: 幂等, 不再改文件、不再备份、不再 reload
        before_commands = len(self.runner.argv_log)
        second = d.install_nginx()
        self.assertFalse(second["changed"])
        self.assertEqual(paths.nginx_site_conf.read_text(encoding="utf-8"), migrated)
        self.assertEqual(len(list(backup_dir.glob(paths.nginx_site_conf.name + ".bak-*"))), 1,
                         "第二次 install 不得再写 backup")
        after = self.runner.argv_log[before_commands:]
        self.assertEqual([c for c in after if "nginx" in c], [], "幂等路径不得再校验/reload nginx")
        self.assertEqual([c for c in after if c[0] != "install"], [], "幂等路径不得再执行其他命令")

    def test_install_fails_closed_on_unknown_architecture(self) -> None:
        paths = self.env(bootstrapped=False)
        unknown = SITE_CONF_FIXTURE.replace("proxy_pass http://127.0.0.1:8000;\n", "")
        paths.nginx_site_conf.write_text(unknown, encoding="utf-8")
        d = self.make(paths=paths)

        with self.assertRaises(DeployError):
            d.install_nginx()
        self.assertEqual(paths.nginx_site_conf.read_text(encoding="utf-8"), unknown, "拒绝时不得改文件")
        for cmd in self.commands():
            self.assertNotIn("-s reload", cmd)

    def test_install_rolls_back_site_config_when_validation_fails(self) -> None:
        paths = self.env(bootstrapped=False)
        original = paths.nginx_site_conf.read_text(encoding="utf-8")
        runner = FakeRunner(FakeWorld(), paths, validate_code=1)
        d = self.make(paths=paths, runner=runner)

        with self.assertRaises(DeployError):
            d.install_nginx()
        self.assertEqual(paths.nginx_site_conf.read_text(encoding="utf-8"), original, "校验失败必须回滚")
        self.assertIn("install.site_config.rolled_back", d.event_names())
        for cmd in self.commands():
            self.assertNotIn("-s reload", cmd)

    def test_install_dry_run_writes_nothing(self) -> None:
        paths = self.env(bootstrapped=False)
        original = paths.nginx_site_conf.read_text(encoding="utf-8")
        d = self.make(paths=paths, dry_run=True)

        result = d.install_nginx()
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(paths.nginx_site_conf.read_text(encoding="utf-8"), original)
        self.assertFalse((paths.nginx_gen_dir / "blue.conf").exists())
        self.assertEqual(self.runner.argv_log, [])


if __name__ == "__main__":
    unittest.main()
