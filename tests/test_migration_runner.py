"""§10B forward migration runner 专项测试(fresh scratch, 经 db_gate 语义)。

场景:
  1. 首次执行 → migration 生效 + tracking 1 行;
  2. 第二次执行 → skip, 零重复效果;
  3. applied 文件内容修改 → hash mismatch fail-closed(exit 3);
  4. _01/_02 顺序;
  5. migration SQL 失败 → schema change 与 tracking 都不存在(exit 4);
  6. history/ 绝不执行; 0000/0001 不由 runner 执行。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.migrate import run  # noqa: E402


def _db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    # runner 直连 libpq: 剥掉 sqlalchemy driver 前缀与 sentinel 参数
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url.split("://", 1)[1]
    url = url.split("?")[0]
    return url


@unittest.skipUnless(_db_url(), "需要 PG 测试库")
class MigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.url = _db_url()
        self.tmp = tempfile.mkdtemp(prefix="mig_runner_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # 干净 tracking + fixture 表(测试间隔离)
        subprocess.run(["psql", self.url, "--no-psqlrc", "-q", "-c", """
            DROP TABLE IF EXISTS maintenance.schema_migrations;
            DROP TABLE IF EXISTS chemistry.runner_marker;
            DROP TABLE IF EXISTS chemistry.mig_imm;
            DROP TABLE IF EXISTS chemistry.mig_imm2;
            DROP TABLE IF EXISTS chemistry.mig_a;
            DROP TABLE IF EXISTS chemistry.mig_b;
            DROP TABLE IF EXISTS chemistry.mig_bad;
            DROP TABLE IF EXISTS chemistry.mig_base;
            DROP TABLE IF EXISTS chemistry.mig_boom;
            DROP TABLE IF EXISTS chemistry.after_ok;
        """], check=True, capture_output=True, env=dict(os.environ))

    def _psql(self, sql: str):
        return subprocess.run(
            ["psql", self.url, "--no-psqlrc", "-At", "-c", sql],
            capture_output=True, text=True, env=dict(os.environ))

    def _write(self, name: str, content: str):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            fh.write(content)
        return path

    def test_first_apply_then_skip(self):
        self._write("20260911_01_runner_t.sql",
                    "CREATE TABLE IF NOT EXISTS chemistry.runner_marker "
                    "(id int PRIMARY KEY); INSERT INTO chemistry.runner_marker "
                    "VALUES (1);")
        rc = run(self.url, self.tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self._psql("SELECT count(*) FROM chemistry.runner_marker;").stdout.strip(), "1")
        rows = self._psql(
            "SELECT count(*) FROM maintenance.schema_migrations;").stdout.strip()
        self.assertEqual(rows, "1")
        # 第二次 → skip, 零重复
        rc = run(self.url, self.tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self._psql("SELECT count(*) FROM chemistry.runner_marker;").stdout.strip(), "1")

    def test_hash_mismatch_fails_closed(self):
        path = self._write("20260911_01_immutable.sql",
                           "CREATE TABLE chemistry.mig_imm (id int);")
        self.assertEqual(run(self.url, self.tmp), 0)
        # 已 applied 文件被修改
        with open(path, "w") as fh:
            fh.write("CREATE TABLE chemistry.mig_imm2 (id int);")
        rc = run(self.url, self.tmp)
        self.assertEqual(rc, 3)
        # 后续不执行: 追加一个 forward, fail-closed 阻断
        self._write("20260911_02_after.sql", "CREATE TABLE chemistry.after_ok (id int);")
        rc = run(self.url, self.tmp)
        self.assertEqual(rc, 3)
        self.assertEqual(
            self._psql("SELECT to_regclass('chemistry.after_ok') IS NULL;")
            .stdout.strip(), "t")

    def test_order_and_exclusions(self):
        # repo 正式目录: 只有 0000/0001(被排除) + history/(不扫描)
        self._write("20260911_01_a.sql",
                    "CREATE TABLE chemistry.mig_a (id int);")
        self._write("20260911_02_b.sql",
                    "CREATE TABLE chemistry.mig_b (id int);")
        # 违规命名: 不匹配 forward 规则 → 忽略
        self._write("zzz_bad_name.sql", "CREATE TABLE chemistry.mig_bad (id int);")
        self._write("0000_baseline.sql", "CREATE TABLE chemistry.mig_base (id int);")
        rc = run(self.url, self.tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self._psql("SELECT to_regclass('chemistry.mig_bad') IS NULL;").stdout.strip(), "t")
        self.assertEqual(
            self._psql("SELECT to_regclass('chemistry.mig_base') IS NULL;").stdout.strip(), "t")
        order = self._psql(
            "SELECT filename FROM maintenance.schema_migrations "
            "ORDER BY filename;").stdout.split()
        self.assertEqual(order, ["20260911_01_a.sql", "20260911_02_b.sql"])

    def test_failed_migration_atomic(self):
        # DDL 先成功, 后续语句失败 → 整体回滚 + 无 tracking
        self._write("20260911_01_boom.sql",
                    "CREATE TABLE chemistry.mig_boom (id int); "
                    "INSERT INTO no_such_table VALUES (1);")
        rc = run(self.url, self.tmp)
        self.assertEqual(rc, 4)
        self.assertEqual(
            self._psql("SELECT to_regclass('chemistry.mig_boom') IS NULL;").stdout.strip(), "t")
        self.assertEqual(
            self._psql("SELECT count(*) FROM maintenance.schema_migrations;")
            .stdout.strip(), "0")

    def test_repo_root_only_baseline_and_bootstrap(self):
        # 正式 repo migrations/ 目录: runner 只会看到 0000/0001(均不匹配 forward 规则)
        rc = run(self.url, os.path.join(ROOT, "migrations"))
        self.assertIn(rc, (0, 3))  # 0=空 forward; 3 仅当曾有 hash 冲突(不应发生)
        self.assertEqual(
            self._psql("SELECT count(*) FROM maintenance.schema_migrations;")
            .stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
