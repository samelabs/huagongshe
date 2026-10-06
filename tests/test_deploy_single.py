"""R4-SINGLE 回归锁(12 条最小集)。

冻结单实例部署契约: 固定端口/固定 worker ID/无 generation 产物/root fail-closed/
readiness 三件套/public smoke/pm2 save/failure 非零。
"""

from __future__ import annotations

import io
import contextlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ops.deploy as D  # noqa: E402
from tests.deploy_fakes import FakeRunner  # noqa: E402


def _ok_world() -> FakeRunner:
    r = FakeRunner()
    r.http_ok_urls = {D.API_HEALTH, D.WEB_HEALTH}
    return r


class RootGuardTests(unittest.TestCase):
    """1. root mutating deploy fail-closed。"""

    def test_deploy_as_root_fail_closed(self):
        with mock.patch.object(D.os, "geteuid", return_value=0):
            with self.assertRaises(D.DeployError) as cm:
                D.deploy(runner=FakeRunner(), skip_build=True)
            self.assertIn("sudo python -m ops.deploy", str(cm.exception))
            self.assertIn("deployment user", str(cm.exception))

    def test_error_message_no_hardcoded_username(self):
        with mock.patch.object(D.os, "geteuid", return_value=0):
            with self.assertRaises(D.DeployError) as cm:
                D.require_non_root()
            self.assertNotIn("ubuntu", str(cm.exception))


class CanonicalContractTests(unittest.TestCase):
    """2-7. canonical 契约 + 无 generation 产物。"""

    def test_api_port_8000(self):
        self.assertEqual(D.API_PORT, 8000)
        self.assertEqual(D.API_HEALTH, "http://127.0.0.1:8000/api/health")

    def test_web_port_3001(self):
        self.assertEqual(D.WEB_PORT, 3001)
        self.assertEqual(D.WEB_HEALTH, "http://127.0.0.1:3001/api/health")

    def test_canonical_apps_and_worker_id(self):
        self.assertEqual(D.CANONICAL_APPS,
                         ("huagongshe-api", "huagongshe", "huagongshe-pubchem-worker"))
        spec = (D.REPO / "ecosystem.config.cjs").read_text()
        self.assertIn('HGS_WORKER_ID: "server-local-1"', spec)
        self.assertNotIn("server-local-1-green", spec)
        self.assertNotIn("server-local-1-blue", spec)
        self.assertIn('HGS_WORKAPI_URL: "http://127.0.0.1:8000"', spec)

    def test_deploy_generates_no_generation_spec(self):
        r = _ok_world()
        with mock.patch.object(D, "wait_http_ok", side_effect=lambda url, **k: url in r.http_ok_urls), \
             mock.patch.object(D, "wait_worker_online", return_value=True), \
             mock.patch.object(D.os, "geteuid", return_value=1000), \
             mock.patch.object(D, "public_smoke", return_value=True):
            self.assertTrue(D.deploy(runner=r, skip_build=True))
        starts = r.pm2_start_only_cmds()
        for c in starts:
            self.assertTrue(c[2].endswith("ecosystem.config.cjs"),
                            f"必须使用 canonical spec: {c}")
            self.assertNotIn("green", c[2])
            self.assertNotIn("blue", c[2])
            self.assertNotIn("ecosystem-green", "".join(c))
            self.assertNotIn("ecosystem-blue", "".join(c))

    def test_deploy_never_touches_nginx_generation_symlink(self):
        r = _ok_world()
        with mock.patch.object(D, "wait_http_ok", side_effect=lambda url, **k: url in r.http_ok_urls), \
             mock.patch.object(D, "wait_worker_online", return_value=True), \
             mock.patch.object(D.os, "geteuid", return_value=1000), \
             mock.patch.object(D, "public_smoke", return_value=True):
            self.assertTrue(D.deploy(runner=r, skip_build=True))
        for c in r.argv_log:
            joined = " ".join(c)
            self.assertNotIn("active.conf", joined)
            self.assertNotIn("generations", joined)
            self.assertNotIn("nginx -s reload", joined)

    def test_no_generation_model_remains(self):
        src = (D.REPO / "ops" / "deploy.py").read_text()
        for token in ("GENERATIONS", "active_link", "--to green", "--to blue",
                      "render_spec", "next-blue", "next-green",
                      "drain_and_stop", "start_generation"):
            self.assertNotIn(token, src, f"generation 残留: {token}")

    def test_next_config_single_dist_dir(self):
        cfg = (D.REPO / "web" / "next.config.ts").read_text()
        self.assertNotIn("HGS_NEXT_DIST_DIR", cfg)
        self.assertNotIn("distDir", cfg)


class ReadinessAndSmokeTests(unittest.TestCase):
    """8-11. readiness 三件套 + smoke + pm2 save。"""

    def _run_deploy(self, r):
        with mock.patch.object(D, "wait_http_ok", side_effect=lambda url, **k: url in r.http_ok_urls), \
             mock.patch.object(D, "wait_worker_online",
                               side_effect=lambda *a, **k: D.worker_online(r)), \
             mock.patch.object(D.os, "geteuid", return_value=1000), \
             mock.patch.object(D, "public_smoke", return_value=True):
            return D.deploy(runner=r, skip_build=True)

    def test_api_readiness_gate(self):
        r = _ok_world()
        r.http_ok_urls = set()          # API 不 ready
        self.assertFalse(self._run_deploy(r))

    def test_web_readiness_gate(self):
        r = _ok_world()
        r.http_ok_urls = {D.API_HEALTH}  # 只 API ready
        self.assertFalse(self._run_deploy(r))

    def test_worker_online_gate_errored_stays_errored(self):
        # errored 且 restart 无法拉起 → worker 不 online → FAIL
        r = _ok_world()
        r.apps = {"huagongshe-pubchem-worker": {"status": "errored"}}
        r.restart_fail = {"huagongshe-pubchem-worker"}
        self.assertFalse(self._run_deploy(r))

    def test_worker_missing_gate(self):
        # worker 缺失且 start 注定失败(spec 无 app) → FAIL
        r = _ok_world()
        r.spec_apps = ("huagongshe-api", "huagongshe")
        self.assertFalse(self._run_deploy(r))

    def test_jlist_failure_fail_closed(self):
        r = _ok_world()
        r.jlist_fail = True
        self.assertFalse(self._run_deploy(r))

    def test_success_path_starts_three_apps_and_saves(self):
        r = _ok_world()
        self.assertTrue(self._run_deploy(r))
        self.assertEqual(set(r.apps), set(D.CANONICAL_APPS))
        self.assertTrue(r.pm2_save_called())
        # 每条 start 只含单 --only + canonical app
        for c in r.pm2_start_only_cmds():
            onlys = [c[i + 1] for i, x in enumerate(c) if x == "--only"]
            self.assertEqual(len(onlys), 1)
            self.assertIn(onlys[0], D.CANONICAL_APPS)

    def test_public_smoke_included(self):
        r = _ok_world()
        with mock.patch.object(D, "public_smoke", return_value=False) as sm, \
             mock.patch.object(D, "wait_http_ok", side_effect=lambda url, **k: url in r.http_ok_urls), \
             mock.patch.object(D, "wait_worker_online", return_value=True), \
             mock.patch.object(D.os, "geteuid", return_value=1000):
            self.assertFalse(D.deploy(runner=r, skip_build=True))
            sm.assert_called_once()


class PublicSmokeContractTests(unittest.TestCase):
    """12. public smoke 契约: canonical HTTPS URL + fail closed(不真实访问公网)。"""

    def test_public_smoke_url_is_canonical_https(self):
        self.assertEqual(D.PUBLIC_SMOKE_URL, "https://huagongshe.com/api/health")
        self.assertNotIn("127.0.0.1", D.PUBLIC_SMOKE_URL)

    def test_public_smoke_success_returns_true(self):
        # mock http_ok, 零真实网络访问
        with mock.patch.object(D, "http_ok", return_value=(True, "status=200")):
            self.assertTrue(D.public_smoke())

    def test_public_smoke_public_failure_fail_closed(self):
        # 公网 health 非 ok(非 200/网络错误/异常 body) → deploy False
        for fail in ((False, "status=502"), (False, "RemoteDisconnected(...)")):
            with mock.patch.object(D, "http_ok", return_value=fail), \
                 mock.patch.object(D, "wait_http_ok", return_value=True), \
                 mock.patch.object(D, "wait_worker_online", return_value=True), \
                 mock.patch.object(D.os, "geteuid", return_value=1000):
                self.assertFalse(D.deploy(runner=FakeRunner(), skip_build=True),
                                 f"public health failure must fail deploy: {fail}")

    def test_public_smoke_hits_canonical_url_only(self):
        with mock.patch.object(D, "http_ok",
                               return_value=(True, "status=200")) as h:
            D.public_smoke()
            h.assert_called_once_with(D.PUBLIC_SMOKE_URL)


class WorkerStabilityGateTests(unittest.TestCase):
    """R4.1 1.4: worker readiness 需同 pid 连续稳定 >=3s, restart 循环不得误判 ready。"""

    def test_restart_loop_not_ready(self):
        import ops.deploy as D
        r = FakeRunner()
        r.apps = {"huagongshe-pubchem-worker": {"status": "online", "pid": 100}}
        call = {"n": 0}

        class Cycling(FakeRunner):
            def run(self, argv):
                res = super().run(argv)
                if argv[:2] == ["pm2", "jlist"]:
                    call["n"] += 1
                    # 每次 jlist pid 都变 = restart 循环
                    self.apps["huagongshe-pubchem-worker"]["pid"] = 200 + call["n"]
                return res

        cyc = Cycling()
        cyc.apps = dict(r.apps)
        self.assertFalse(D.wait_worker_online(cyc, timeout=1.0, poll=0.05,
                                              stable_seconds=0.2))

    def test_stable_online_ready(self):
        import ops.deploy as D
        r = FakeRunner()
        r.apps = {"huagongshe-pubchem-worker": {"status": "online", "pid": 100}}
        self.assertTrue(D.wait_worker_online(r, timeout=5.0, poll=0.05,
                                             stable_seconds=0.15))

    def test_flapping_status_not_ready(self):
        import ops.deploy as D
        r = FakeRunner()
        r.apps = {"huagongshe-pubchem-worker": {"status": "online", "pid": 100}}
        flip = {"on": True}

        orig = r.run

        def flapping(argv):
            res = orig(argv)
            if argv[:2] == ["pm2", "jlist"]:
                flip["on"] = not flip["on"]
                r.apps["huagongshe-pubchem-worker"]["status"] = (
                    "online" if flip["on"] else "errored")
            return res

        r.run = flapping
        self.assertFalse(D.wait_worker_online(r, timeout=1.0, poll=0.05,
                                              stable_seconds=0.2))


class FailureReportingTests(unittest.TestCase):
    """12. failure 非零, 不伪报 success。"""

    def test_build_failure_returns_false(self):
        r = _ok_world()
        r.build_ok = False
        with mock.patch.object(D.os, "geteuid", return_value=1000):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertFalse(D.deploy(runner=r, skip_build=False))
            self.assertIn("build.failed", buf.getvalue())

    def test_pm2_start_failure_returns_false(self):
        r = _ok_world()
        r.spec_apps = ()   # spec 内无 app → start 失败
        with mock.patch.object(D.os, "geteuid", return_value=1000):
            self.assertFalse(D.deploy(runner=r, skip_build=True))

    def test_cli_exit_nonzero_on_failure(self):
        r = _ok_world()
        r.build_ok = False
        with mock.patch.object(D, "deploy", return_value=False) as dep, \
             mock.patch.object(D.os, "geteuid", return_value=1000):
            dep.side_effect = None
            dep.return_value = False
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(D.main(["--skip-build"]), 1)


if __name__ == "__main__":
    unittest.main()
