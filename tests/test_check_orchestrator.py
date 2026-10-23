"""检查编排器(local/check.py)的保护测试 — 纯函数, 无 docker/DB 依赖。

覆盖四类必须守住的行为:
1. 错误库目标在连接前拒绝(TEST/HGS 双 URL 一致性, scheme/sentinel 差异允许)
   且生成的 run 专有库名落在 db_gate 的名称与哨兵闸内;
2. 空选择与非法定模块在执行前拒绝;
3. unittest 输出定级: 失败/空跑/未许可 skip 不得为 PASS;
4. 清理只碰本 run 登记的资源; dev/build 互斥标记判定。

编排器本身的端到端行为(容器、建库、迁移)由实际运行 docs/TESTING.md 的
入口命令验证, 不在此做镜像测试。
"""
from __future__ import annotations

import contextlib
import io
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_SPEC = importlib.util.spec_from_file_location(
    "check_orchestrator", os.path.join(ROOT, "local", "check.py"))
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)

from tests import db_gate  # noqa: E402
from tests.db_gate import require_test_db  # noqa: E402


def _url(dbname, *, host="db", port=5432, user="hgs_local", sentinel=True):
    url = f"postgresql+asyncpg://{user}:pw@{host}:{port}/{dbname}"
    return url + "?test_sentinel=hgs-test-db" if sentinel else url


class DbTargetConsistencyTests(unittest.TestCase):
    """两个数据库 URL 必须指向同一专有库, 不一致在连接前抛错。"""

    def test_same_target_with_sentinel_diff_accepted(self):
        check.assert_same_target(
            _url("test_hgs_ab12cd34"),
            "postgresql+asyncpg://hgs_local:pw@db:5432/test_hgs_ab12cd34")

    def test_different_database_rejected_before_any_connection(self):
        with self.assertRaises(check.EnvTargetMismatch):
            check.assert_same_target(_url("test_hgs_ab12cd34"),
                                     _url("test_hgs_ffffffff"))

    def test_different_host_rejected(self):
        with self.assertRaises(check.EnvTargetMismatch):
            check.assert_same_target(_url("test_hgs_ab12cd34"),
                                     _url("test_hgs_ab12cd34", host="elsewhere"))

    def test_different_user_rejected(self):
        with self.assertRaises(check.EnvTargetMismatch):
            check.assert_same_target(_url("test_hgs_ab12cd34"),
                                     _url("test_hgs_ab12cd34", user="other"))

    def test_run_db_names_pass_db_gate_name_and_sentinel(self):
        for _ in range(20):
            name = check.run_db_name()
            self.assertRegex(name, db_gate._TEST_DB_NAME_RE)
            url = _url(name)
            with unittest.mock.patch.dict(os.environ,
                                          {"TEST_DATABASE_URL": url}):
                self.assertEqual(require_test_db(), url)


class ModuleSelectionTests(unittest.TestCase):
    def test_empty_selection_rejected(self):
        with self.assertRaises(check.UsageError):
            check.validate_modules([])

    def test_non_module_shapes_rejected(self):
        for bad in ("discover", "tests", "tests/", "./tests/test_x.py",
                    "tests.evil.Name", "api.main"):
            with self.assertRaises(check.UsageError):
                check.validate_modules([bad])

    def test_valid_module_names_accepted(self):
        check.validate_modules(["tests.test_gate", "tests.test_db_gate"])


class VerdictTests(unittest.TestCase):
    def _parsed(self, **overrides):
        parsed = {"ran": 2, "status": "OK",
                  "counts": {"failures": 0, "errors": 0, "skipped": 0,
                             "expected failures": 0, "unexpected successes": 0},
                  "skip_details": [], "xfail_details": []}
        parsed.update(overrides)
        return parsed

    def test_ok_without_skips_passes(self):
        parsed = check.parse_unittest_output(
            "test_a (tests.x.A) ... ok\nRan 2 tests in 0.1s\n\nOK\n")
        self.assertEqual(parsed["ran"], 2)
        self.assertEqual(check.verdict(parsed)["status"], "PASS")

    def test_incomplete_and_unexplained_skips_fail(self):
        for output in ("Ran 1 test in 0.1s\n", "Ran 1 test in 0.1s\nOK (skipped=1)\n"):
            self.assertEqual(check.verdict(check.parse_unittest_output(output))["status"], "FAIL")

    def test_zero_ran_is_failure(self):
        self.assertEqual(
            check.verdict(self._parsed(ran=0))["status"], "FAIL")

    def test_failures_and_errors_fail(self):
        parsed = check.parse_unittest_output(
            "Ran 3 tests in 0.1s\n\nFAILED (failures=1, errors=2)\n")
        self.assertEqual(parsed["counts"]["failures"], 1)
        self.assertEqual(parsed["counts"]["errors"], 2)
        self.assertEqual(check.verdict(parsed)["status"], "FAIL")

    def test_unexpected_success_fails(self):
        parsed = check.parse_unittest_output(
            "Ran 1 test in 0.1s\n\nOK (unexpected successes=1)\n")
        self.assertEqual(check.verdict(parsed)["status"], "FAIL")

    def test_unpermitted_skip_fails_with_case_detail(self):
        text = ("test_h_allow_refresh_false_zero_enqueue "
                "(tests.test_api_privilege_boundary.RefreshUseCasePolicyTests"
                ".test_h_allow_refresh_false_zero_enqueue) ... skipped "
                "'无 stale 样本行'\n"
                "Ran 4 tests in 0.1s\n\nOK (skipped=1)\n")
        parsed = check.parse_unittest_output(text)
        v = check.verdict(parsed)
        self.assertEqual(v["status"], "FAIL")
        self.assertTrue(v["details"])

    def test_permitted_case_level_skip_passes_only_that_case(self):
        case = "tests.m.T.test_a"
        detail = f"{case}: 设计内跳过"
        parsed = self._parsed(ran=9,
                              counts={"failures": 0, "errors": 0, "skipped": 1,
                                      "expected failures": 0,
                                      "unexpected successes": 0},
                              skip_details=[detail])
        self.assertEqual(check.verdict(parsed, [case])["status"], "PASS")
        # 整模块白名单不吸收同模块其他用例的 skip
        other = "tests.m.T.test_another_case: whatever"
        self.assertEqual(
            check.verdict(dict(parsed, skip_details=[other]), [case])["status"],
            "FAIL")

    def test_expected_failure_recorded_not_hidden(self):
        text = ("test_x (tests.m.T.test_x) ... expected failure\n"
                "Ran 1 test in 0.1s\n\nOK (expected failures=1)\n")
        parsed = check.parse_unittest_output(text)
        self.assertEqual(parsed["counts"]["expected failures"], 1)
        self.assertEqual(parsed["xfail_details"], ["tests.m.T.test_x"])
        self.assertEqual(check.verdict(parsed)["status"], "FAIL")
        self.assertEqual(check.verdict(parsed, allowed_xfails=["tests.m.T.test_x"])["status"], "PASS")

    def test_docstring_case_skip_and_xfail_are_recorded(self):
        # unittest -v 实际输出: 带 docstring 的用例结果落在第二行
        text = ("test_a (tests.m.T.test_a) ... skipped 'plain'\n"
                "test_b (tests.m.T.test_b)\n"
                "Has a docstring. ... skipped 'documented'\n"
                "test_c (tests.m.T.test_c)\n"
                "Documented xfail. ... expected failure\n"
                "\n" + "-" * 70 + "\n"
                "Ran 3 tests in 0.0s\n\nOK (skipped=2, expected failures=1)\n")
        parsed = check.parse_unittest_output(text)
        self.assertEqual(parsed["skip_details"], ["tests.m.T.test_a: plain",
                                                  "tests.m.T.test_b: documented"])
        self.assertEqual(parsed["xfail_details"], ["tests.m.T.test_c"])
        self.assertEqual(check.verdict(
            parsed, ["tests.m.T.test_a", "tests.m.T.test_b"],
            ["tests.m.T.test_c"])["status"], "PASS")
        # 许可只覆盖逐项点名的用例
        self.assertEqual(check.verdict(
            parsed, ["tests.m.T.test_a"], ["tests.m.T.test_c"])["status"], "FAIL")


class CleanupOwnershipTests(unittest.TestCase):
    def test_only_registered_resources_are_cleaned(self):
        touched = []

        def executor(kind, ident):
            touched.append((kind, ident))
            return True, None

        check.cleanup_resources(
            [{"kind": "run_db", "ident": "test_hgs_ab12cd34"},
             {"kind": "container_tmpdir", "ident": "/tmp/run-1"}],
            executor)
        self.assertEqual(touched, [("run_db", "test_hgs_ab12cd34"),
                                   ("container_tmpdir", "/tmp/run-1")])

    def test_empty_registry_touches_nothing(self):
        touched = []
        check.cleanup_resources([], lambda kind, ident: touched.append(1))
        self.assertEqual(touched, [])

    def test_cleanup_failure_is_recorded_not_raised(self):
        def boom(kind, ident):
            raise RuntimeError("dropdb 失败")

        results = check.cleanup_resources(
            [{"kind": "run_db", "ident": "test_hgs_ab12cd34"}], boom)
        self.assertFalse(results[0]["cleaned"])
        self.assertIn("dropdb 失败", results[0]["error"])

    def test_unknown_kind_is_refused_not_executed(self):
        # 解析层直接拒绝: 未知类型/通配库名/越界路径拿不到清理动作
        self.assertIsNone(check.resolve_cleanup("wildcard_drop", "test_*"))
        self.assertIsNone(check.resolve_cleanup("run_db", "test_*"))
        self.assertIsNone(check.resolve_cleanup("run_db", "huagongshe"))
        self.assertIsNone(check.resolve_cleanup("container_tmpdir", "/etc"))
        self.assertEqual(check.resolve_cleanup("run_db", "test_hgs_ab12cd34"),
                         ("as_pg", "dropdb --if-exists test_hgs_ab12cd34"))
        self.assertEqual(check.resolve_cleanup("container_tmpdir", "/tmp/r1"),
                         ("docker_rm", "/tmp/r1"))


class DevBuildMutexTests(unittest.TestCase):
    LIVE_PID = 424242  # 只在 _alive 里判活, 不对应真实进程

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dev = os.path.join(self._tmp.name, "dev.json")
        self.build = os.path.join(self._tmp.name, "build.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _alive(self, pid):
        return pid == self.LIVE_PID

    def _write(self, path, pid):
        with open(path, "w") as fh:
            json.dump({"kind": "dev", "pid": pid, "started": "-"}, fh)

    def test_live_dev_pid_blocks_build(self):
        self._write(self.dev, self.LIVE_PID)
        action, _ = check.dev_build_decision(self.dev, self.build, self._alive)
        self.assertEqual(action, "dev_active")

    def test_live_build_pid_blocks_dev(self):
        self._write(self.build, self.LIVE_PID)
        action, _ = check.dev_build_decision(self.dev, self.build, self._alive)
        self.assertEqual(action, "build_active")

    def test_dead_markers_report_stale(self):
        self._write(self.dev, 1)
        self._write(self.build, 2)
        action, _ = check.dev_build_decision(self.dev, self.build, self._alive)
        self.assertEqual(action, "stale")

    def test_no_markers_ok(self):
        action, _ = check.dev_build_decision(self.dev, self.build, self._alive)
        self.assertEqual(action, "ok")

    def test_corrupt_marker_blocks(self):
        with open(self.dev, "w") as fh:
            fh.write("{not json")
        with self.assertRaises(check.BlockedError):
            check.dev_build_decision(self.dev, self.build, self._alive)


class CliGuardTests(unittest.TestCase):
    def test_main_rejects_cwd_outside_repo(self):
        with unittest.mock.patch("os.getcwd", return_value="/not/hgs/tree"):
            code = check.main(["preflight"])
        self.assertEqual(code, check.EXIT_USAGE)

    def test_backend_without_tests_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            check.build_parser().parse_args(["backend"])
        self.assertEqual(ctx.exception.code, check.EXIT_USAGE)

    def test_redact_strips_passwords(self):
        text = "postgresql://u:secretpw@db:5432/x"
        self.assertNotIn("secretpw", check.redact(text))


class ExecutionBoundaryTests(unittest.TestCase):
    def test_denied_host_termination_preserves_resources(self):
        proc = unittest.mock.Mock()
        proc.communicate.side_effect = KeyboardInterrupt()
        proc.poll.return_value = None
        proc.send_signal.side_effect = PermissionError()
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(check, "RUNS_DIR", tmp), \
                unittest.mock.patch.object(check.subprocess, "Popen", return_value=proc), \
                unittest.mock.patch.object(check.os, "killpg", side_effect=PermissionError()):
            run = check.Run("denied-stop")
            with self.assertRaises(check.BlockedError):
                run.exec("command", ["owned-command"])
            self.assertFalse(run.processes_stopped)

    def test_target_rejection_precedes_database_creation(self):
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(check, "RUNS_DIR", tmp), \
                unittest.mock.patch.object(check, "load_stack_env", return_value={"HGS_DB_USER": "fake", "HGS_DB_PASSWORD": "fake"}), \
                unittest.mock.patch.object(check, "require_stack"), \
                unittest.mock.patch.object(check, "verify_tester"), \
                unittest.mock.patch.object(check.Run, "docker", return_value=(0, False, "Python 3.12", "")), \
                unittest.mock.patch.object(check, "build_test_urls", side_effect=check.EnvTargetMismatch("wrong target")), \
                unittest.mock.patch.object(check, "create_run_db") as create:
            args = check.build_parser().parse_args(["backend", "--tests", "tests.test_gate"])
            self.assertEqual(check.cmd_backend(args), 2)
            create.assert_not_called()

    def test_finish_redacts_nested_results_and_console(self):
        secret = "synthetic password @:%"
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(check, "RUNS_DIR", tmp), \
                unittest.mock.patch.object(check, "_RUN_SECRETS", {secret}), \
                contextlib.redirect_stdout(io.StringIO()) as console:
            run = check.Run("redaction")
            run.info("nested", {"error": secret})
            run.finish("BLOCKED", secret)
            payload = open(os.path.join(run.dir, "result.json")).read()
            self.assertNotIn(secret, payload)
            self.assertNotIn(secret, console.getvalue())

    def test_live_build_guard_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev, build = os.path.join(tmp, "dev"), os.path.join(tmp, "build")
            check.write_marker(build, "build")
            with unittest.mock.patch.object(check, "DEV_MARKER", dev), \
                    unittest.mock.patch.object(check, "BUILD_MARKER", build), \
                    unittest.mock.patch.object(check, "port_listening", return_value=False):
                with self.assertRaises(check.BlockedError):
                    check.release_dev_guard(None)


if __name__ == "__main__":
    unittest.main()
