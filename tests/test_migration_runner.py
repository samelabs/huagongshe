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

from scripts.migrate import run, FORWARD_RE  # noqa: E402


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
            DROP TABLE IF EXISTS chemistry.runner_concurrent_once;
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

    def test_concurrent_runners_serialized_by_lock(self):
        """真并发: 两个 runner 子进程同时启动, advisory lock 串行化。

        migration 带 pg_sleep(1) 制造重叠窗口: 若锁无效, 两边几乎同时
        越过 hash check → 一边 INSERT tracking UNIQUE 冲突或表 DDL race
        → 至少一个 runner 非零退出; 锁有效时 B 等 A commit 后重读
        tracking → skip, 双方 0 退出。
        """
        import time
        self._write(
            "20260911_01_concurrent_once.sql",
            "CREATE TABLE chemistry.runner_concurrent_once (id int PRIMARY KEY, "
            "created_by text NOT NULL); "
            "SELECT pg_sleep(1); "
            "INSERT INTO chemistry.runner_concurrent_once "
            "SELECT 1, pg_backend_pid()::text;")
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        script = (
            "import sys; "
            f"sys.path.insert(0, {ROOT!r}); "
            "from scripts.migrate import run; "
            f"sys.exit(run({self.url!r}, {self.tmp!r}))")
        # 真同时启动两个独立 runner 进程
        procs = [subprocess.Popen(
            [sys.executable, "-c", script], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)]
        outs = [p.communicate(timeout=120) for p in procs]
        rcs = [p.returncode for p in procs]
        # 两个 runner 都必须正常结束
        self.assertEqual(rcs, [0, 0],
                         f"runner 退出码 {rcs}: {[o[1] for o in outs]}")
        # business effect 只有一次
        self.assertEqual(
            self._psql("SELECT count(*), count(DISTINCT created_by) "
                       "FROM chemistry.runner_concurrent_once;").stdout.strip(),
            "1|1")
        # tracking 恰 1 行
        self.assertEqual(
            self._psql("SELECT count(*) FROM maintenance.schema_migrations "
                       "WHERE filename='20260911_01_concurrent_once.sql';")
            .stdout.strip(), "1")
        # skip 路径被走到: 两个进程输出里恰一个 applied
        applied_lines = sum(
            o for o in [outs[0][0].count("[runner] applied"),
                        outs[1][0].count("[runner] applied")])
        skip_lines = sum(
            o for o in [outs[0][0].count("[runner] skip"),
                        outs[1][0].count("[runner] skip")])
        self.assertEqual(applied_lines, 1)
        self.assertEqual(skip_lines, 1)

    def test_repo_forward_chain_contains_pubchem_identity_reconciliation(self):
        # 正式 repo migrations/: reconciliation migration 存在于合法 forward 集合
        # (未来 forward migration 会自然增加, 不断言"恰一条")。
        RECONCILE = "20260910_01_reconcile_pubchem_identity_jobs.sql"
        fwd = sorted(
            f for f in os.listdir(os.path.join(ROOT, "migrations"))
            if FORWARD_RE.match(f)
        )
        self.assertIn(RECONCILE, fwd)
        # 文件单一职责: 幂等 reconciliation DDL, 无 backfill/无 enqueue
        sql = open(os.path.join(ROOT, "migrations", RECONCILE)).read()
        self.assertIn("CREATE TABLE IF NOT EXISTS maintenance.pubchem_identity_jobs", sql)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS pubchem_identity_jobs_dedupe_idx", sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_claim_idx", sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_chem_idx", sql)
        self.assertNotIn("INSERT INTO", sql)
        # runner owns transaction: forward migration 顶层不得含事务控制
        # (psql --single-transaction 遇脚本自身 BEGIN/COMMIT/ROLLBACK 失效)
        for line in sql.splitlines():
            stripped = line.strip().rstrip(";").strip().upper()
            self.assertNotIn(stripped, {"BEGIN", "COMMIT", "ROLLBACK"},
                             f"transaction control in forward migration: {line!r}")
        # runner 对 fresh scratch 库执行全部 forward 并记录 tracking
        rc = run(self.url, os.path.join(ROOT, "migrations"))
        self.assertIn(rc, (0, 3))
        tracked = self._psql(
            "SELECT filename FROM maintenance.schema_migrations;"
        ).stdout.split()
        self.assertIn(RECONCILE, tracked)
        # reconciliation 幂等: 表与三个冻结索引存在
        idx = self._psql("""
            SELECT count(*) FROM pg_indexes WHERE schemaname='maintenance'
            AND tablename='pubchem_identity_jobs';
        """).stdout.strip()
        self.assertEqual(idx, "4")  # pkey + dedupe + claim + chem


if __name__ == "__main__":
    unittest.main()
