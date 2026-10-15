"""测试库身份闸的反向用例。

铁律: 任何 DB 集成测试在建 engine 之前必须先过闸 —— 生产形状的库名、
缺 sentinel、错误 sentinel 三种情形都要在连接建立之前被拒绝。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.db_gate import ProductionDbBlocked, require_test_db
from tests.db_gate import test_db_or_skip as _test_db_or_skip

VALID_URL = (
    "postgresql+asyncpg://u:p@localhost:55433/test_hgs"
    "?test_sentinel=hgs-test-db"
)


class RequireTestDbRejectsBeforeEngineTests(unittest.TestCase):
    """三种不合规 URL 必须在建 engine 之前抛 ProductionDbBlocked。"""

    def test_production_shaped_db_name_rejected(self):
        url = "postgresql+asyncpg://u:p@localhost:5432/huagongshe?test_sentinel=hgs-test-db"
        with patch.dict(os.environ, {"TEST_DATABASE_URL": url}):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_missing_sentinel_rejected(self):
        url = "postgresql+asyncpg://u:p@localhost:55433/hgs-test-db"
        with patch.dict(os.environ, {"TEST_DATABASE_URL": url}):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_wrong_sentinel_rejected(self):
        url = "postgresql+asyncpg://u:p@localhost:55433/hgs-test-db?test_sentinel=hgs-production-db"
        with patch.dict(os.environ, {"TEST_DATABASE_URL": url}):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_unset_env_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_valid_url_passes(self):
        with patch.dict(os.environ, {"TEST_DATABASE_URL": VALID_URL}):
            self.assertEqual(require_test_db(), VALID_URL)

    def test_skip_entrypoint_raises_skiptest(self):
        import unittest as _ut
        with patch.dict(os.environ, {"TEST_DATABASE_URL": "postgresql+asyncpg://u:p@h/huagongshe"}):
            with self.assertRaises(_ut.SkipTest):
                _test_db_or_skip()


class GateBeforeEngineContractTests(unittest.TestCase):
    """DB 集成测试文件必须先过闸、后建 engine(源码顺序断言)。"""

    FILES = (
        "tests/test_token_plaintext_contract.py",
        "tests/test_token_revoke_idempotency.py",
        "tests/test_pubchem_jobs_index_contract.py",
    )

    def test_gate_call_precedes_engine_creation(self):
        for rel in self.FILES:
            with self.subTest(file=rel):
                source = Path(rel).read_text()
                gate_pos = source.find("test_db_or_skip()")
                engine_pos = source.find("create_async_engine")
                self.assertGreater(gate_pos, -1, "必须调用 test_db_or_skip()")
                self.assertGreater(engine_pos, -1, "文件应创建 engine")
                self.assertLess(
                    gate_pos, engine_pos,
                    "测试库闸必须先于 create_async_engine 执行")
                self.assertNotIn(
                    'os.environ.get("TEST_DATABASE_URL"',
                    source.split("def ")[0],
                    "不得绕过闸门直接读环境变量建 engine")


if __name__ == "__main__":
    unittest.main()
