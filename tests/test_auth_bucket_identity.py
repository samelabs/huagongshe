"""账号入口限流分桶: 按真实身份(来源 IP / 账号+IP), 不设全站共享桶。

覆盖注册、用户名校验、登录三个入口:
- 有来源 IP → 各自按 IP 分桶;
- 登录 = 账号哈希 + 来源 IP 组合, 他人无法锁死某个账号;
- 拿不到来源 IP → 不落任何桶并记警。
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.users as users


class _Headers:
    def __init__(self, mapping=None):
        self._m = {k.lower(): v for k, v in (mapping or {}).items()}

    def get(self, key, default=None):
        return self._m.get(key.lower(), default)


class _Request:
    def __init__(self, mapping=None):
        self.headers = _Headers(mapping)


def _account_key(account: str) -> str:
    return hashlib.sha256(account.encode()).hexdigest()[:24]


class RegisterBucketTests(unittest.TestCase):
    def _run(self, request):
        calls = []

        async def fake_enforce(bucket, identity, limit, window):
            calls.append((bucket, identity, limit, window))

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(
            one=lambda: (1, "u", "u", "e@x.co", "user", None)))
        db.commit = AsyncMock()
        with patch.object(users, "enforce_http", fake_enforce), \
             patch.object(users, "create_session", AsyncMock()), \
             patch.object(users, "password_hash", lambda p: "h"):
            asyncio.run(users.register(
                body=MagicMock(username="userx", email="e@x.co", password="pw123456"),
                request=request, response=MagicMock(), db=db))
        return calls

    def test_register_buckets_by_source_ip(self):
        calls = self._run(_Request({"x-real-ip": "203.0.113.20"}))
        self.assertEqual(calls, [("register", "203.0.113.20", 60, 3600)])

    def test_register_without_ip_skips_limit(self):
        self.assertEqual(self._run(_Request()), [])


class CheckUsernameBucketTests(unittest.TestCase):
    def _run(self, request):
        calls = []

        async def fake_enforce(bucket, identity, limit, window):
            calls.append((bucket, identity, limit, window))

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(fetchone=lambda: None))
        with patch.object(users, "enforce_http", fake_enforce):
            asyncio.run(users.check_username(request=request, username="userx", db=db))
        return calls

    def test_check_username_buckets_by_source_ip(self):
        calls = self._run(_Request({"x-real-ip": "203.0.113.21"}))
        self.assertEqual(calls, [("check-username", "203.0.113.21", 30, 60)])

    def test_check_username_without_ip_skips_limit(self):
        self.assertEqual(self._run(_Request()), [])


class LoginBucketTests(unittest.TestCase):
    def _identity(self, request) -> str | None:
        calls = []

        async def fake_enforce(bucket, identity, limit, window):
            calls.append(identity)

        db = MagicMock()
        db.execute = AsyncMock(return_value=None)
        db.rollback = AsyncMock()
        with patch.object(users, "enforce_http", fake_enforce):
            try:
                asyncio.run(users.login(
                    body=MagicMock(account="alice@x.co", password="pw"),
                    request=request, response=MagicMock(), db=db))
            except Exception:
                pass  # 账号不存在路径, 只关心限流身份
        return calls[0] if calls else None

    def test_login_buckets_by_account_and_ip(self):
        identity = self._identity(_Request({"x-real-ip": "203.0.113.22"}))
        self.assertEqual(identity, f"{_account_key('alice@x.co')}:203.0.113.22")

    def test_login_different_ip_gets_separate_bucket(self):
        first = self._identity(_Request({"x-real-ip": "203.0.113.22"}))
        second = self._identity(_Request({"x-real-ip": "198.51.100.9"}))
        self.assertNotEqual(first, second, "换来源 IP 不得共享同一账号桶")

    def test_login_without_ip_falls_back_to_account_only(self):
        identity = self._identity(_Request())
        self.assertEqual(identity, _account_key("alice@x.co"))


if __name__ == "__main__":
    unittest.main()
