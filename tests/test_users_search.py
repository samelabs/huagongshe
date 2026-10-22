""" — GET /users/search 针对性测试。

覆盖: username 前缀(不区分大小写)、display_name 包含(不区分大小写)、
username 完全匹配排第一、停用用户不出现、公开字段口径(bio 截断 120/
follower_count/is_following)、分页上限(422)、空白 q 422、限流(429)。
直调 endpoint 函数 + 真链测试库(与 test_oauth_connections_manage 同法)。
"""
from __future__ import annotations

import re
import time
import types
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ASYNC_URL = None
try:
    from tests.db_gate import test_db_or_skip
    _raw = test_db_or_skip()
except Exception:
    _raw = None

if _raw:
    _u = urlparse(_raw)
    assert parse_qs(_u.query).get("test_sentinel") in (
        ["hgs-test-db"], ["hgs-ephemeral-db"])
    ASYNC_URL = re.sub(
        r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

if ASYNC_URL:
    from fastapi import HTTPException
    from api.core.security import Actor
    import api.users as users_api


def _frozen_limiter_clock():
    """限流是固定窗口：连打循环跨过窗口边界会被拆进两个桶。冻结引擎时钟于
    当前窗口中点，循环内全部请求计入同一窗口。"""
    now = (int(time.time()) // 60) * 60 + 30
    return patch("api.core.rate_limit.time", types.SimpleNamespace(time=lambda: now))


class _FakeRequest:
    def __init__(self, xff=None, real_ip=None):
        headers = {}
        if xff:
            headers["x-forwarded-for"] = xff
        if real_ip:
            headers["x-real-ip"] = real_ip
        self.headers = headers


def _actor(user_id: int) -> Actor:
    return Actor(user_id, "u", "U", "u@example.test", "member", None, "session")


@unittest.skipUnless(ASYNC_URL, "测试库闸")
class UsersSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:8]
        async with self.engine.begin() as conn:
            self.prefix = f"usqa_{self.tag}"
            # 三个活跃用户: 前缀命中 / 显示名包含 / 完全等于查询词
            ids = {}
            for username, display, bio in (
                (f"{self.prefix}_alice", "Alice Chemist", "x" * 200),
                (f"{self.prefix}_bob", f"Boo {self.tag} Display", None),
                (f"zz_{self.tag}_exact", f"Exact {self.tag}", "bio"),
                (f"zz_{self.tag}_exactor", f"Exactor {self.tag}", None),
            ):
                ids[username] = int((await conn.execute(text("""
                    INSERT INTO community.users(username,email,password_hash,display_name,bio)
                    VALUES (:u,:u||'@example.test','x',:d,:b) RETURNING id
                """), {"u": username, "d": display, "b": bio})).scalar_one())
            # 停用用户: 不得出现
            ids["disabled"] = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name,status)
                VALUES (:u,:u||'@example.test','x','Disabled','disabled') RETURNING id
            """), {"u": f"{self.prefix}_gone"})).scalar_one())
            # 关注关系: alice 关注 exact → 登录 alice 时 is_following
            await conn.execute(text("""
                INSERT INTO community.user_follows(follower_user_id,followed_user_id)
                VALUES (:a,:b)
            """), {"a": ids[f"{self.prefix}_alice"],
                   "b": ids[f"zz_{self.tag}_exact"]})
            await conn.execute(text("""
                INSERT INTO community.user_follows(follower_user_id,followed_user_id)
                VALUES (:a,:b)
            """), {"a": ids["disabled"], "b": ids[f"{self.prefix}_alice"]})
        self.ids = ids
        await self._flush_rate_limit()

    async def test_search_username_profile_has_unambiguous_http_route(self):
        import httpx
        from api.main import app
        from api.core.database import get_db
        owner = self.ids[f"{self.prefix}_alice"]
        async with self.engine.begin() as db:
            await db.execute(text("UPDATE community.users SET username='search' WHERE id=:id"), {"id": owner})
        async def session():
            async with self.Session() as db:
                yield db
        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = session
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                profile = await client.get("/api/users/by-username/search")
                self.assertEqual(profile.status_code, 200)
                self.assertEqual(profile.json()["username"], "search")
                self.assertEqual((await client.get("/api/users/search", params={"q": "search"})).status_code, 200)
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous

    async def _flush_rate_limit(self):
        import redis.asyncio as redis
        from api.core.config import settings
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            keys = await client.keys("rate:users-search:*")
            if keys:
                await client.delete(*keys)
        except Exception:
            pass
        finally:
            await client.aclose()

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "DELETE FROM community.user_follows WHERE follower_user_id=ANY(:ids)"
                " OR followed_user_id=ANY(:ids)"),
                {"ids": list(self.ids.values())})
            await conn.execute(text(
                "DELETE FROM community.users WHERE id=ANY(:ids)"),
                {"ids": list(self.ids.values())})
        await self.engine.dispose()

    async def _search(self, q, *, actor=None, page=1, page_size=20,
                      xff=None, real_ip=None):
        async with self.Session() as db:
            return await users_api.search_users(
                request=_FakeRequest(xff=xff, real_ip=real_ip), q=q, page=page,
                page_size=page_size, actor=actor, db=db)

    async def test_prefix_match_case_insensitive(self):
        result = await self._search(self.prefix.upper())
        usernames = {u["username"] for u in result["users"]}
        self.assertIn(f"{self.prefix}_alice", usernames)
        self.assertIn(f"{self.prefix}_bob", usernames)
        self.assertNotIn(f"{self.prefix}_gone", usernames)  # 停用不出现
        self.assertEqual(result["total"], len(result["users"]))

    async def test_display_name_contains(self):
        result = await self._search(f"Boo {self.tag}")
        usernames = [u["username"] for u in result["users"]]
        self.assertEqual(usernames, [f"{self.prefix}_bob"])

    async def test_exact_username_ranks_first(self):
        # "zz_{tag}_exact" 前缀同时命中 exact 与 exactor(包含), 完全匹配排第一
        result = await self._search(f"zz_{self.tag}_exact")
        usernames = [u["username"] for u in result["users"]]
        self.assertEqual(usernames[0], f"zz_{self.tag}_exact")
        self.assertIn(f"zz_{self.tag}_exactor", usernames)

    async def test_public_fields_and_bio_truncation(self):
        result = await self._search(self.prefix.upper())
        alice = next(u for u in result["users"]
                     if u["username"] == f"{self.prefix}_alice")
        self.assertEqual(set(alice.keys()),
                         {"username", "display_name", "avatar_url", "active",
                          "bio", "follower_count", "is_following"})
        self.assertEqual(len(alice["bio"]), 120)  # 200 字截断
        self.assertEqual(alice["follower_count"], 1)  # disabled 用户的关注也计
        self.assertFalse(alice["is_following"])  # 匿名恒 False
        bob = next(u for u in result["users"]
                   if u["username"] == f"{self.prefix}_bob")
        self.assertIsNone(bob["bio"])

    async def test_is_following_when_logged_in(self):
        result = await self._search(
            f"zz_{self.tag}", actor=_actor(self.ids[f"{self.prefix}_alice"]))
        exact = next(u for u in result["users"]
                     if u["username"] == f"zz_{self.tag}_exact")
        self.assertTrue(exact["is_following"])

    async def test_like_wildcards_are_literal(self):
        # % 与 _ 是数据不是通配符: 任意 tag 查询 + % 不得放大命中
        result = await self._search(self.prefix + "%")
        self.assertEqual({u["username"] for u in result["users"]}, set())

    async def test_blank_query_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            await self._search("   ")
        self.assertEqual(raised.exception.status_code, 422)

    def test_pagination_query_contract(self):
        # Query 契约(直调绕过 FastAPI 校验, 断言声明本身): page 1..50,
        # page_size 默认 20、上限 50 —— 分页不超 50 页 × 50 行。
        import inspect
        from fastapi import params as fastapi_params
        from annotated_types import Ge, Le

        def bounds(query):
            ge = next(m.ge for m in query.metadata if isinstance(m, Ge))
            le = next(m.le for m in query.metadata if isinstance(m, Le))
            return ge, le

        sig = inspect.signature(users_api.search_users)
        page = sig.parameters["page"].default
        page_size = sig.parameters["page_size"].default
        self.assertIsInstance(page, fastapi_params.Query)
        self.assertIsInstance(page_size, fastapi_params.Query)
        self.assertEqual(bounds(page), (1, 50))
        self.assertEqual(bounds(page_size), (1, 50))
        self.assertEqual(page_size.default, 20)

    async def test_anonymous_rate_limit_per_ip(self):
        # 同一匿名 IP 连打 61 次 → 429(Redis 真实闸门); 分桶键是 nginx
        # 覆盖写入的 x-real-ip, 与请求自带的 x-forwarded-for 无关。
        limited = False
        with _frozen_limiter_clock():
            for _ in range(61):
                try:
                    await self._search(self.prefix, real_ip="198.51.100.77")
                except HTTPException as exc:
                    limited = exc.status_code == 429
                    break
        self.assertTrue(limited, "匿名 61 次/分钟必须被限流")

    async def test_forged_xff_does_not_affect_bucketing(self):
        # XFF 首段是客户端可伪造的值 —— 每次换一个伪造 XFF, 若分桶
        # 错误地读 XFF 则永不超限; 读 x-real-ip 时同一 IP 61 次必 429。
        limited = False
        with _frozen_limiter_clock():
            for i in range(61):
                try:
                    await self._search(
                        self.prefix, real_ip="198.51.100.78",
                        xff=f"1.2.3.{i}, 10.0.0.1")
                except HTTPException as exc:
                    limited = exc.status_code == 429
                    break
        self.assertTrue(limited, "伪造 XFF 不得绕过按 IP 限流")

    async def test_no_real_ip_skips_limit_without_shared_unknown_bucket(self):
        # 拿不到 x-real-ip 时不落 "unknown" 全站共用桶 —— 80 次(超过
        # 单桶 60/min 上限)全部放行, 并记告警(生产 nginx 必写该头)。
        with self.assertLogs("api.users", level="WARNING") as logs:
            for _ in range(80):
                await self._search(self.prefix, xff="9.9.9.9")
        self.assertTrue(
            any("client IP" in line for line in logs.output),
            "缺 x-real-ip 应记告警")


if __name__ == "__main__":
    unittest.main()
