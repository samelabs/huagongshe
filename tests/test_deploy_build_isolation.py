"""E8/B1: 每一代必须有自己的 Next 构建产物。

  blue  → build 与 `next start` 都用 `.next-blue`
  green → build 与 `next start` 都用 `.next-green`
构建目标代不得写坏正在服务的旧代产物; PM2 runtime env 必须与 build 用同一个值。

residual risk(已知并接受): 源码 / `public` 等目录仍共享 —— E8 只保证
generation-specific Next build artifact, 不是完全不可变的 release 目录。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.deploy import GENERATIONS, Deployer, spec_substitutions  # noqa: E402
from tests.deploy_fakes import (  # noqa: E402
    FakeProber,
    FakeRunner,
    FakeWorld,
    make_env,
    write_active_link,
)


class BuildIsolationCase(unittest.TestCase):
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
    def dist(self, gen: str) -> Path:
        return self.paths.web_dir / f".next-{gen}"

    def seed_artifact(self, gen: str, content: str) -> str:
        d = self.dist(gen)
        d.mkdir(parents=True, exist_ok=True)
        (d / "BUILD_ID").write_text(content, encoding="utf-8")
        return content

    def artifact(self, gen: str) -> str:
        return (self.dist(gen) / "BUILD_ID").read_text(encoding="utf-8")

    def build_envs(self) -> list[dict]:
        return [
            dict(e or {})
            for a, e in zip(self.runner.argv_log, self.runner.env_log)
            if a[:2] == [str(self.paths.npm_bin), "run"]
        ]

    def spec(self, gen: str) -> str:
        self.d.render_spec(GENERATIONS[gen])
        return (self.paths.state_dir / f"ecosystem-{gen}.config.cjs").read_text(encoding="utf-8")


class BuildTargetTests(BuildIsolationCase):
    def test_building_green_writes_only_next_green(self) -> None:
        before_blue = self.seed_artifact("blue", "blue-old\n")
        d = self.deployer()

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual([b["dist"] for b in self.runner.builds], [".next-green"])
        self.assertEqual([b["cwd"] for b in self.runner.builds], [str(self.paths.web_dir)])
        self.assertTrue((self.dist("green") / "BUILD_ID").exists())
        self.assertEqual(self.artifact("blue"), before_blue, "构建目标代不得动旧代产物")
        self.assertFalse((self.paths.web_dir / ".next").exists(), "不得回落到共享 .next")

    def test_building_blue_writes_only_next_blue(self) -> None:
        # 现网 = green → 目标 = blue
        write_active_link(self.paths, "green")
        self.world.start("green")
        self.world.set_active("green")
        self.world.delete("blue")
        before_green = self.seed_artifact("green", "green-old\n")
        d = self.deployer()

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["active"], "blue")
        self.assertEqual([b["dist"] for b in self.runner.builds], [".next-blue"])
        self.assertTrue((self.dist("blue") / "BUILD_ID").exists())
        self.assertEqual(self.artifact("green"), before_green, "构建目标代不得动旧代产物")

    def test_build_env_matches_runtime_env_in_pm2_spec(self) -> None:
        d = self.deployer()

        d.deploy()

        envs = self.build_envs()
        self.assertEqual(len(envs), 1)
        self.assertEqual(envs[0]["HGS_NEXT_DIST_DIR"], ".next-green")
        spec = (self.paths.state_dir / "ecosystem-green.config.cjs").read_text(encoding="utf-8")
        self.assertIn('HGS_NEXT_DIST_DIR: ".next-green"', spec, "PM2 runtime env 必须与 build 同值")
        # 目标代的 api/web/worker 全部指向本代端口, 不串代
        self.assertIn("--port 8010", spec)
        self.assertIn("-p 3011", spec)
        self.assertIn('API_ORIGIN_INTERNAL: "http://127.0.0.1:8010"', spec)

    def test_each_generation_spec_points_at_its_own_artifact(self) -> None:
        d = self.deployer()

        green_spec = self.spec("green")
        blue_spec = self.spec("blue")

        self.assertIn('HGS_NEXT_DIST_DIR: ".next-green"', green_spec)
        self.assertNotIn('HGS_NEXT_DIST_DIR: ".next-blue"', green_spec)
        self.assertIn('HGS_NEXT_DIST_DIR: ".next-blue"', blue_spec)
        self.assertNotIn('HGS_NEXT_DIST_DIR: ".next-green"', blue_spec)

    def test_skip_build_still_points_runtime_at_generation_artifact(self) -> None:
        d = self.deployer(skip_build=True)

        result = d.deploy()

        self.assertTrue(result["ok"], result)
        self.assertEqual(self.runner.builds, [], "skip-build 不得构建")
        spec = (self.paths.state_dir / "ecosystem-green.config.cjs").read_text(encoding="utf-8")
        self.assertIn('HGS_NEXT_DIST_DIR: ".next-green"', spec)

    def test_dist_dirs_are_generation_specific(self) -> None:
        self.assertEqual(GENERATIONS["blue"].next_dist_dir, ".next-blue")
        self.assertEqual(GENERATIONS["green"].next_dist_dir, ".next-green")
        self.assertNotEqual(GENERATIONS["blue"].next_dist_dir, GENERATIONS["green"].next_dist_dir)

    def test_next_config_reads_the_same_env_var_the_spec_sets(self) -> None:
        cfg = (REPO_ROOT / "web" / "next.config.ts").read_text(encoding="utf-8")
        self.assertIn("distDir", cfg)
        self.assertIn("process.env.HGS_NEXT_DIST_DIR", cfg)
        joined = "\n".join(r for _a, r, _c in spec_substitutions(GENERATIONS["green"], self.paths))
        self.assertIn('HGS_NEXT_DIST_DIR: ".next-green"', joined)
        self.assertIn('HGS_NEXT_DIST_DIR: ".next-blue"', "\n".join(
            r for _a, r, _c in spec_substitutions(GENERATIONS["blue"], self.paths)
        ))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
