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

    def test_worker_restarts_only_after_fronting_apps_ready(self):
        """worker 重启必须发生在 API/Web health 就绪之后 —— worker 启动
        preflight 鉴权(/workapi/v1/jobs/lease)依赖 API, 提前重启只会
        exit 1 crash-loop。"""
        r = _ok_world()
        timeline: list[str] = []

        class _RecordingRunner:
            def run(self, argv):
                if argv[:2] in (["pm2", "start"], ["pm2", "restart"]):
                    target = (argv[argv.index("--only") + 1]
                              if "--only" in argv else argv[2])
                    timeline.append(f"pm2:{target}")
                return r.run(argv)

        def _record_wait(url, **k):
            which = ("api" if url == D.API_HEALTH
                     else "web" if url == D.WEB_HEALTH else url)
            timeline.append(f"ready:{which}")
            return url in r.http_ok_urls

        with mock.patch.object(D, "wait_http_ok", side_effect=_record_wait), \
             mock.patch.object(D, "wait_worker_online",
                               side_effect=lambda *a, **k: D.worker_online(r)), \
             mock.patch.object(D.os, "geteuid", return_value=1000), \
             mock.patch.object(D, "public_smoke", return_value=True):
            self.assertTrue(D.deploy(runner=_RecordingRunner(), skip_build=True))

        self.assertEqual(
            timeline,
            ["pm2:huagongshe-api", "pm2:huagongshe",
             "ready:api", "ready:web",
             "pm2:huagongshe-pubchem-worker"],
            "部署顺序: 先重启 API/Web → 就绪 → 才重启 worker")

    def test_worker_not_restarted_when_api_never_ready(self):
        """API 迟迟不就绪时, worker 不得被重启(crash-loop 根因)。"""
        r = _ok_world()
        r.http_ok_urls = set()  # API 永不 ready
        self.assertFalse(self._run_deploy(r))
        targets = []
        for c in r.argv_log:
            if c[:2] in (["pm2", "start"], ["pm2", "restart"]) and "--only" in c:
                targets.append(c[c.index("--only") + 1])
        self.assertNotIn("huagongshe-pubchem-worker", targets,
                         "API 未就绪就重启 worker 会 crash-loop")

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

    @staticmethod
    def _fake_public_http(ok_pages=True, version=None):
        """公网冒烟替身: 覆盖 health/页面/MCP 三类请求, 零真实网络访问。

        返回 (http_ok, http_200, post_json) 三个 MagicMock, 供断言调用面。
        """
        if version is None:
            version = (D.REPO / "VERSION").read_text(encoding="utf-8").strip()
        sse = ("event: message\n"
               f'data: {{"jsonrpc":"2.0","id":1,"result":'
               f'{{"serverInfo":{{"name":"huagongshe","version":"{version}"}}}}}}\n\n')
        http_200 = mock.MagicMock(return_value=((True, "status=200") if ok_pages
                                                else (False, "error=fake")))
        post_json = mock.MagicMock(return_value=((200, sse) if ok_pages
                                                 else (503, "")))
        http_ok = mock.MagicMock(return_value=(True, "status=200"))
        return http_ok, http_200, post_json

    def test_public_smoke_success_returns_true(self):
        # 全部请求走替身, 零真实网络访问
        http_ok, http_200, post_json = self._fake_public_http()
        with mock.patch.object(D, "http_ok", http_ok), \
             mock.patch.object(D, "_http_200", http_200), \
             mock.patch.object(D, "_http_post_json", post_json):
            self.assertTrue(D.public_smoke())

    def test_public_smoke_requests_every_page_and_mcp(self):
        # 五语言首页 + 化合物详情页 + MCP initialize 都必须被请求(替身记录)
        http_ok, http_200, post_json = self._fake_public_http()
        with mock.patch.object(D, "http_ok", http_ok), \
             mock.patch.object(D, "_http_200", http_200), \
             mock.patch.object(D, "_http_post_json", post_json):
            D.public_smoke()
        page_urls = [c.args[0] for c in http_200.call_args_list]
        for locale in D.SMOKE_LOCALES:
            self.assertIn(f"https://huagongshe.com/{locale}", page_urls)
        self.assertIn(D.SMOKE_CHEMICAL_PAGE, page_urls)
        post_json.assert_called_once()
        self.assertEqual(post_json.call_args.args[0], D.SMOKE_MCP_URL)
        self.assertEqual(
            post_json.call_args.args[2]["Accept"],
            "application/json, text/event-stream")

    def test_public_smoke_mcp_version_mismatch_fails(self):
        http_ok, http_200, post_json = self._fake_public_http(version="0.0.0")
        with mock.patch.object(D, "http_ok", http_ok), \
             mock.patch.object(D, "_http_200", http_200), \
             mock.patch.object(D, "_http_post_json", post_json):
            self.assertFalse(D.public_smoke())

    def test_public_smoke_page_failure_fail_closed(self):
        http_ok, http_200, post_json = self._fake_public_http(ok_pages=False)
        with mock.patch.object(D, "http_ok", http_ok), \
             mock.patch.object(D, "_http_200", http_200), \
             mock.patch.object(D, "_http_post_json", post_json):
            self.assertFalse(D.public_smoke())

    def test_public_smoke_never_touches_real_network(self):
        # 单测禁止访问外网: 替身之外, urlopen 一旦被调用即失败。
        http_ok, http_200, post_json = self._fake_public_http()
        with mock.patch.object(D, "http_ok", http_ok), \
             mock.patch.object(D, "_http_200", http_200), \
             mock.patch.object(D, "_http_post_json", post_json):
            import urllib.request
            guard = mock.patch.object(
                urllib.request, "urlopen",
                side_effect=AssertionError("单测不得访问外网"))
            with guard:
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
            h.assert_called_once_with(D.PUBLIC_SMOKE_URL,
                                      headers=D.PUBLIC_SMOKE_HEADERS)

    def test_public_smoke_probe_ua_identity(self):
        # UA 表达真实身份(化工社 deploy smoke probe), 非浏览器伪装
        self.assertEqual(
            D.PUBLIC_SMOKE_HEADERS,
            {"User-Agent": "Huagongshe-Deploy-Smoke/1.0"},
        )

    def test_readiness_urls_do_not_use_smoke_headers(self):
        # generic readiness(loopback API/WEB health)保持无 headers 现行为
        for url in (D.API_HEALTH, D.WEB_HEALTH):
            with mock.patch.object(D, "http_ok",
                                   return_value=(True, "status=200")) as h:
                D.http_ok(url)
                h.assert_called_once_with(url)

    def test_http_ok_headers_reach_urllib_request(self):
        # 直接证明: headers=... 时构造 urllib.request.Request 并携带 headers,
        # 而非只测 public_smoke 传参。mock urlopen 捕获真实入参, 零公网访问。
        import urllib.request as _ur
        captured = {}

        class _FakeResp:
            status = 200

            def read(self, n=-1):
                return b'{"status":"ok"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            captured["timeout"] = timeout
            return _FakeResp()

        import urllib.request
        headers = {"User-Agent": "Huagongshe-Deploy-Smoke/1.0"}
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=fake_urlopen):
            ok, detail = D.http_ok("https://example.invalid/api/health",
                                   headers=headers)
        self.assertTrue(ok, detail)
        req = captured["req"]
        self.assertIsInstance(req, _ur.Request)
        self.assertEqual(req.get_header("User-agent"),
                         "Huagongshe-Deploy-Smoke/1.0")
        # timeout 语义不变(透传)
        self.assertEqual(captured["timeout"], 5.0)

    def test_http_ok_without_headers_keeps_plain_url(self):
        # 未提供 headers: 仍传裸 URL 字符串, loopback readiness 行为零变化
        captured = {}

        class _FakeResp:
            status = 200

            def read(self, n=-1):
                return b'{"status":"ok"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _FakeResp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok, _ = D.http_ok("http://127.0.0.1:8000/api/health")
        self.assertTrue(ok)
        self.assertIsInstance(captured["req"], str)


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

    def test_build_command_is_npm_ci_only(self):
        """发布构建只允许 npm ci —— 不得回退 npm install（锁文件可重现）。"""
        r = _ok_world()
        with mock.patch.object(D, "wait_http_ok", side_effect=lambda url, **k: url in r.http_ok_urls), \
             mock.patch.object(D, "wait_worker_online", return_value=True), \
             mock.patch.object(D.os, "geteuid", return_value=1000), \
             mock.patch.object(D, "public_smoke", return_value=True):
            self.assertTrue(D.deploy(runner=r, skip_build=False))
        build_cmds = [argv for argv in r.argv_log
                      if argv[0] == "bash" and "next build" in (argv[-1] or "")]
        self.assertEqual(len(build_cmds), 1)
        script = build_cmds[0][-1]
        self.assertIn("npm ci", script)
        self.assertNotIn("npm install", script)

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


class ChildEnvTests(unittest.TestCase):
    """子进程不继承调用方终端环境(pm2 --update-env 会写进 app 与 dump)。"""

    def test_child_env_drops_caller_terminal_vars(self):
        caller = {"PATH": "/home/x/agent/venv/bin:/usr/bin", "HOME": "/home/ubuntu",
                  "PM2_HOME": "/home/ubuntu/.pm2", "TMPDIR": "/home/x/scratch",
                  "SSL_CERT_FILE": "/home/x/cacert.pem", "SSH_AUTH_SOCK": "/run/s",
                  "GIT_PAGER": "cat", "SOME_API_KEY": "k"}
        with mock.patch.dict(D.os.environ, caller, clear=True):
            env = D.child_env()
        self.assertEqual(env["PATH"], D.CHILD_PATH)
        self.assertEqual(env["HOME"], "/home/ubuntu")
        self.assertEqual(env["PM2_HOME"], "/home/ubuntu/.pm2")
        self.assertEqual(set(env) - {"PATH", "LANG", "HOME", "USER", "LOGNAME", "PM2_HOME"}, set())

    def test_real_runner_passes_child_env(self):
        with mock.patch.object(D.subprocess, "run") as run:
            D.Runner.real().run(["pm2", "jlist"])
        self.assertEqual(run.call_args.kwargs["env"], D.child_env())


if __name__ == "__main__":
    unittest.main()
