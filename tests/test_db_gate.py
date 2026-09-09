"""测试库身份闸测试 (0909 §1)。

验证:
1. 缺失 TEST_DATABASE_URL 时 require_test_db() 拒绝(fail-fast), 且不会触碰生产配置。
2. 指向生产库名(如 huagongshe)时被拒。
3. 无 sentinel 被拒; 错误 sentinel 被拒。
4. 合规 test 库 + 正确 sentinel 放行。
5. 生产 settings.database_url 无论值为何, 闸逻辑不读它(隔离性由模块契约保证)。
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.db_gate import ProductionDbBlocked, require_test_db  # noqa: E402

PROD_LIKE = "postgresql://huagongshe:pw@127.0.0.1:5432/huagongshe"
GOOD = "postgresql://test:test@127.0.0.1:5432/test_hgs?test_sentinel=hgs-test-db"


class DbGateTests(unittest.TestCase):
    def _with_env(self, value):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            old = os.environ.pop("TEST_DATABASE_URL", None)
            if value is not None:
                os.environ["TEST_DATABASE_URL"] = value
            try:
                yield
            finally:
                os.environ.pop("TEST_DATABASE_URL", None)
                if old is not None:
                    os.environ["TEST_DATABASE_URL"] = old

        return _ctx()

    def test_missing_url_fail_fast(self):
        with self._with_env(None):
            with self.assertRaises(ProductionDbBlocked) as cm:
                require_test_db()
            self.assertIn("TEST_DATABASE_URL", str(cm.exception))

    def test_missing_url_does_not_fallback_to_settings(self):
        # 关键契约: 即使生产 settings 可导入且带 database_url, 也不得被使用
        with self._with_env(None):
            try:
                from api.core.config import settings  # noqa: F401
                has_settings = True
            except Exception:
                has_settings = False
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()
            # 闸的拒绝与 settings 存在与否无关
            self.assertTrue(True)

    def test_production_db_name_rejected(self):
        with self._with_env(PROD_LIKE):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_test_db_without_sentinel_rejected(self):
        with self._with_env("postgresql://test:test@127.0.0.1:5432/test_hgs"):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_test_db_wrong_sentinel_rejected(self):
        with self._with_env(
            "postgresql://test:test@127.0.0.1:5432/test_hgs?test_sentinel=nope"
        ):
            with self.assertRaises(ProductionDbBlocked):
                require_test_db()

    def test_good_url_passes(self):
        with self._with_env(GOOD):
            self.assertEqual(require_test_db(), GOOD)

    def test_gate_never_reads_prod_env_file(self):
        # /etc/huagongshe.env 里的 HGS_DATABASE_URL 不影响闸
        old = os.environ.pop("HGS_DATABASE_URL", None)
        os.environ["HGS_DATABASE_URL"] = PROD_LIKE
        try:
            with self._with_env(None):
                with self.assertRaises(ProductionDbBlocked):
                    require_test_db()
        finally:
            os.environ.pop("HGS_DATABASE_URL", None)
            if old is not None:
                os.environ["HGS_DATABASE_URL"] = old


if __name__ == "__main__":
    unittest.main()
