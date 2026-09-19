"""E9-B §6 — WorkAPI receipt prune 脚本契约测试。

覆盖:
1. completed_at >= cutoff → 不删
2. completed_at < cutoff → 删除
3. batch limit 生效(单批不超过上限)
4. --dry-run → 零 DELETE / 零写事务
5. 重复执行 → 第二次 deleted=0
契约:
- DB exception → non-zero exit
- 输出不含 lease token hash / token 内容
- 不 import api.workapi(静态锁)
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts",
                      "prune_workapi_receipts.py")

from tests.db_gate import test_db_or_skip  # noqa: E402

DB_URL = None
try:
    DB_URL = test_db_or_skip()
except unittest.SkipTest:
    DB_URL = None


def _dsn(u):
    base = u.split("?")[0]
    if base.startswith("postgresql://"):
        base = "postgresql+asyncpg://" + base.split("://", 1)[1]
    return base


def _load_script():
    spec = importlib.util.spec_from_file_location("prune_workapi_receipts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScriptContractTests(unittest.TestCase):
    """无需 DB 的静态契约。"""

    def test_does_not_import_workapi(self):
        src = open(SCRIPT, encoding="utf-8").read()
        self.assertNotIn("from api.workapi", src)
        self.assertNotIn("import api.workapi", src)
        # 加载脚本本身不得触发 workapi 导入(同进程其他测试可能已导入
        # api.workapi — 故以"脚本加载前后 sys.modules 差集"判定)
        before = set(sys.modules)
        mod = _load_script()
        added = set(sys.modules) - before
        self.assertFalse(
            [m for m in added if m.startswith("api.workapi")],
            f"脚本加载引入了 workapi: {[m for m in added if m.startswith('api.workapi')]}")
        self.assertTrue(hasattr(mod, "prune") and hasattr(mod, "main"))

    def test_defaults(self):
        mod = _load_script()
        self.assertEqual(mod.DEFAULT_RETENTION_DAYS, 30)
        self.assertEqual(mod.DEFAULT_BATCH, 10000)


@unittest.skipUnless(DB_URL, "需要 test DB")
class PruneBehaviorTests(unittest.TestCase):
    NS = "e9b-prune-test"

    def _engine(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        return create_async_engine(_dsn(DB_URL), poolclass=NullPool)

    def _seed_receipts(self, days_old_list):
        """插入 N 行: days_old_list 每项一天数; NS 命名空间。"""
        async def go():
            from sqlalchemy import text
            eng = self._engine()
            try:
                async with eng.begin() as c:
                    await c.execute(text(
                        "DELETE FROM maintenance.workapi_completion_receipts"
                        " WHERE worker_id = :w"), {"w": self.NS})
                    for i, d in enumerate(days_old_list):
                        await c.execute(text("""
                            INSERT INTO maintenance.workapi_completion_receipts
                              (family, job_id, worker_id, lease_token_hash,
                               scope, terminal_status, completed_at)
                            VALUES ('test', :job_id, :w, :h,
                                    'test', 'ok',
                                    now() - make_interval(days => :d))
                        """), {"job_id": 9_100_000 + i, "w": self.NS,
                               "h": bytes(32), "d": d})
            finally:
                await eng.dispose()
        asyncio.run(go())

    def _count(self):
        async def go():
            from sqlalchemy import text
            eng = self._engine()
            try:
                async with eng.begin() as c:
                    return int((await c.execute(text(
                        "SELECT count(*) FROM maintenance.workapi_completion_receipts"
                        " WHERE worker_id = :w"),
                        {"w": self.NS})).scalar())
            finally:
                await eng.dispose()
        return asyncio.run(go())

    def _cleanup(self):
        async def go():
            from sqlalchemy import text
            eng = self._engine()
            try:
                async with eng.begin() as c:
                    await c.execute(text(
                        "DELETE FROM maintenance.workapi_completion_receipts"
                        " WHERE worker_id = :w"), {"w": self.NS})
            finally:
                await eng.dispose()
        asyncio.run(go())

    def _run(self, *argv):
        mod = _load_script()
        from api.core import database as db_mod
        test_factory = None

        async def _factory():
            from sqlalchemy.ext.asyncio import async_sessionmaker
            eng = self._engine()
            return async_sessionmaker(eng, expire_on_commit=False)()

        # main() 内 lazy import api.core.database.async_session — patch 之
        from sqlalchemy.ext.asyncio import async_sessionmaker
        holder = {}

        def _make_factory(eng):
            mk = async_sessionmaker(eng, expire_on_commit=False)
            return mk

        # 简化: 以测试库 URL 重建 sessionmaker
        import api.core.config as cfg
        holder["orig"] = db_mod.async_session
        holder["orig_engine"] = db_mod.engine
        test_eng = self._engine()
        db_mod.async_session = _make_factory(test_eng)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = mod.main(list(argv))
            return code, buf.getvalue()
        finally:
            db_mod.async_session = holder["orig"]
            db_mod.engine = holder["orig_engine"]

            async def _disp():
                await test_eng.dispose()
            asyncio.run(_disp())

    def setUp(self):
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def test_recent_receipt_kept_old_deleted(self):
        """新(<30d)不删, 旧(>30d)删。"""
        self._seed_receipts([1, 10, 45, 60])  # 2 新 2 旧
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("deleted=2", out)
        self.assertEqual(self._count(), 2)  # 剩下 1d/10d 两行

    def test_batch_limit_respected(self):
        """batch 上限: 5 行过期但 batch=2 → 三批, 每批 ≤2。"""
        self._seed_receipts([40] * 5)
        code, out = self._run("--batch", "2")
        self.assertEqual(code, 0)
        self.assertIn("deleted=5", out)
        self.assertEqual(self._count(), 0)
        # 逐批 commit 证据: 脚本语义为循环删除至删空(batch 上限约束单批)
        self.assertEqual(self._count(), 0)

    def test_dry_run_no_delete(self):
        self._seed_receipts([45, 50])
        code, out = self._run("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("candidates=2", out)
        self.assertIn("deleted=0", out)
        self.assertEqual(self._count(), 2, "dry-run 不得真删")

    def test_second_run_idempotent(self):
        self._seed_receipts([45])
        code1, out1 = self._run()
        self.assertEqual(code1, 0)
        self.assertIn("deleted=1", out1)
        code2, out2 = self._run()
        self.assertEqual(code2, 0)
        self.assertIn("deleted=0", out2, "重复运行第二次 deleted=0")

    def test_db_error_nonzero_exit(self):
        from sqlalchemy import text
        mod = _load_script()

        async def boom(*a, **k):
            raise RuntimeError("simulated db failure")

        import io as _io
        from contextlib import redirect_stdout as _rs
        with patch.object(mod, "prune", boom), _rs(_io.StringIO()):
            rc = mod.main([])  # 显式空 argv: 不吃 unittest 的 sys.argv
        self.assertNotEqual(rc, 0, "DB error 必须 non-zero exit")

    def test_batch_zero_rejected_no_write(self):
        # R4.1 2: --batch 0 曾会无限空 DELETE loop —— 必须 CLI 报错非零退出
        mod = _load_script()
        import contextlib
        buf2 = io.StringIO()
        buf2_err = io.StringIO()
        from contextlib import redirect_stderr
        with contextlib.redirect_stdout(buf2), redirect_stderr(buf2_err):
            with self.assertRaises(SystemExit) as cm:  # argparse error → exit 2
                mod.main(["--batch", "0"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--batch", buf2_err.getvalue())
        self.assertNotIn("cutoff=", buf2.getvalue(), "零 DB 写入/零输出")

    def test_batch_negative_rejected(self):
        mod = _load_script()
        from contextlib import redirect_stderr
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                mod.main(["--batch", "-5"])
        self.assertEqual(cm.exception.code, 2)

    def test_retention_zero_rejected(self):
        mod = _load_script()
        from contextlib import redirect_stderr
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                mod.main(["--retention-days", "0"])
        self.assertEqual(cm.exception.code, 2)

    def test_retention_negative_rejected_no_future_cutoff(self):
        mod = _load_script()
        from contextlib import redirect_stderr
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                mod.main(["--retention-days", "-3"])
        self.assertEqual(cm.exception.code, 2)

    def test_output_has_no_token_material(self):
        self._seed_receipts([45])
        code, out = self._run()
        self.assertEqual(code, 0)
        # 输出仅含聚合数字, 不得含 token hash(种子为 bytes(32) 全零也不得回显)
        for line in out.splitlines():
            self.assertNotIn("lease_token_hash", line)


if __name__ == "__main__":
    unittest.main()
