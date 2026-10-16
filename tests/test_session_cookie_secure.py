"""会话 cookie 的 Secure 标记：默认开启，只有显式配置才关闭（本地局域网 http 调试）。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

# api.core.config 在模块层实例化 Settings()（版本号读取等），import 即需要
# HGS_DATABASE_URL —— 本文件自带 CI synthetic 值，使测试脱离外部环境可跑。
os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:5432/unused")


class SessionCookieSecureTests(unittest.TestCase):
    def test_default_is_secure(self):
        from api.core.config import Settings
        with mock.patch.dict(os.environ, {"HGS_DATABASE_URL": "postgresql+asyncpg://u:p@h/d"}, clear=False):
            os.environ.pop("HGS_SESSION_COOKIE_SECURE", None)
            self.assertTrue(Settings(_env_file=None).session_cookie_secure)

    def test_env_can_disable_for_local_http(self):
        from api.core.config import Settings
        with mock.patch.dict(os.environ, {"HGS_DATABASE_URL": "postgresql+asyncpg://u:p@h/d", "HGS_SESSION_COOKIE_SECURE": "false"}):
            self.assertFalse(Settings(_env_file=None).session_cookie_secure)


if __name__ == "__main__":
    unittest.main()
