"""测试库身份闸 (0909 规范收口 §1)。

铁律:
- DB integration tests 只允许连 TEST_DATABASE_URL, 绝不 fallback 生产 settings/env。
- 未显式设置 TEST_DATABASE_URL → fail-fast(ImportError), 不是静默跑。
- 测试库身份保护双保险: 数据库名模式 + 显式 sentinel(允许名单), 两关全过才放行。

用法 (测试文件):
    from tests.db_gate import require_test_db
    DB_URL = require_test_db()   # 不合规直接抛异常, 不会连生产
"""

from __future__ import annotations

import os
import re
import sys

# ---------------------------------------------------------------------------
# 允许的测试库名模式 (数据库名必须匹配其一)
# ---------------------------------------------------------------------------
_TEST_DB_NAME_RE = re.compile(
    r"^(test|tmp|ephemeral|ut)[-_a-z0-9]*$"  # test_xxx / tmp_xxx / ut_xxx
)

# 显式 sentinel: 测试库必须带 ?test_sentinel=... 且值在名单内
_SENTINELS = ("hgs-test-db", "hgs-ephemeral-db")


class ProductionDbBlocked(RuntimeError):
    """测试试图连接生产库 — 配置错误, 必须 fail-fast。"""


def _db_name(url: str) -> str:
    # postgres://user:pass@host:port/dbname?params
    m = re.match(r"^[a-zA-Z0-9+]+://[^/]+/([^?/]+)", url)
    return m.group(1) if m else ""


def _sentinel(url: str) -> str | None:
    m = re.search(r"[?&]test_sentinel=([^&]+)", url)
    return m.group(1) if m else None


def require_test_db() -> str:
    """返回合规 TEST_DATABASE_URL; 任何不合规抛 ProductionDbBlocked。"""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise ProductionDbBlocked(
            "TEST_DATABASE_URL 未设置: DB integration tests 必须显式指定测试库, "
            "禁止 fallback 到生产 settings/database_url。"
        )
    name = _db_name(url)
    # 双保险 1: 数据库名模式
    if not _TEST_DB_NAME_RE.match(name):
        raise ProductionDbBlocked(
            f"TEST_DATABASE_URL 指向的库 '{name}' 不符合测试库名模式 "
            f"(须 test/tmp/ephemeral/ut 前缀): 拒绝连接。"
        )
    # 双保险 2: 显式 sentinel
    s = _sentinel(url)
    if s not in _SENTINELS:
        raise ProductionDbBlocked(
            f"TEST_DATABASE_URL 缺少有效 test_sentinel 参数 "
            f"(允许: {_SENTINELS}): 拒绝连接。"
        )
    return url


def test_db_or_skip():
    """unittest 兼容入口: 合规返回 URL, 否则 raise unittest.SkipTest。"""
    import unittest
    try:
        return require_test_db()
    except ProductionDbBlocked as e:
        raise unittest.SkipTest(f"测试库闸: {e}") from e


# 直接执行时自检: 当前环境能否过闸
if __name__ == "__main__":
    try:
        u = require_test_db()
        print(f"OK: {u}")
    except ProductionDbBlocked as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        sys.exit(1)
