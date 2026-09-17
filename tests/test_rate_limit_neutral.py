"""G2.R rate-limit core neutralization tests.

覆盖:
- Neutral core: 无 FastAPI import(结构断言); enforce/lease/structure gate
  抛 neutral 语义异常(不依赖 FastAPI 即可测试)
- HTTP bridge: RateLimited→429+Retry-After+X-RateLimit-Remaining:0;
  LimiterUnavailable→503; ResourceBusy→429+Retry-After:5
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://governance:governance@127.0.0.1:5432/unused",
)

from api.core import rate_limit as rl  # noqa: E402
from api.core.rate_limit import (  # noqa: E402
    LimiterUnavailable, RateLimited, RateLimitError, ResourceBusy,
)


async def _consume_ok(*_a, **_k):
    return 5, 0, True


async def _consume_disallowed(*_a, **_k):
    return 0, 0, False


async def _consume_redis_dead(*_a, **_k):
    raise ConnectionError("redis gone")


async def _lease_ok(bucket, identity, limit, ttl_seconds=30):
    return True


async def _lease_busy(bucket, identity, limit, ttl_seconds=30):
    return False


async def _noop_exit(held, bucket="structure-search"):
    return None


class _FakeEvalRedis:
    """redis.Redis 替身: eval 返回可配置结果。"""

    result = [1, 1]
    raise_exc: Exception | None = None

    def __init__(self, connection_pool=None):
        pass

    async def eval(self, *_a, **_k):
        if _FakeEvalRedis.raise_exc:
            raise _FakeEvalRedis.raise_exc
        return _FakeEvalRedis.result


class NeutralCoreStructureTests(unittest.TestCase):
    """core 不 import fastapi/starlette, 无 HTTPException/Response 引用。"""

    def test_no_framework_import(self):
        tree = ast.parse((REPO / "api" / "core" / "rate_limit.py").read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            self.assertFalse(roots & {"fastapi", "starlette", "mcp", "uvicorn"},
                             f"rate_limit.py 不得导入 {roots}")
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                ids.add(node.id)
            elif isinstance(node, ast.Attribute):
                ids.add(node.attr)
        for banned in ("HTTPException", "Response", "ToolError"):
            self.assertNotIn(banned, ids)

    def test_exception_payload_has_no_http_semantics(self):
        exc = RateLimited("请求过于频繁，请稍后重试", retry_after=42)
        self.assertEqual(exc.detail, "请求过于频繁，请稍后重试")
        self.assertEqual(exc.retry_after, 42)
        self.assertFalse(hasattr(exc, "status_code"))
        self.assertFalse(hasattr(exc, "headers"))


class NeutralCoreBehaviorTests(unittest.TestCase):
    def test_enforce_allowed_passes(self):
        with patch.object(rl, "consume", _consume_ok):
            asyncio.run(rl.enforce("t", "u", 10, 60))  # 不抛即通过

    def test_enforce_over_limit_raises_ratelimited_with_retry_after(self):
        with patch.object(rl, "consume", _consume_disallowed):
            with self.assertRaises(RateLimited) as ctx:
                asyncio.run(rl.enforce("t", "u", 10, 60))
        self.assertEqual(ctx.exception.detail, "请求过于频繁，请稍后重试")
        self.assertGreaterEqual(ctx.exception.retry_after, 1)

    def test_enforce_redis_failure_raises_limiter_unavailable(self):
        with patch.object(rl, "consume", _consume_redis_dead):
            with self.assertRaises(LimiterUnavailable) as ctx:
                asyncio.run(rl.enforce("t", "u", 10, 60))
        self.assertEqual(ctx.exception.detail, "限速服务暂时不可用，请稍后重试")
        self.assertIsNone(ctx.exception.retry_after)

    def test_acquire_lease_success_returns_true(self):
        _FakeEvalRedis.result = [1, 1]
        _FakeEvalRedis.raise_exc = None
        with patch.object(rl.redis, "Redis", _FakeEvalRedis):
            self.assertTrue(asyncio.run(rl.acquire_lease("t", "g", 4)))

    def test_acquire_lease_busy_returns_false_no_exception(self):
        _FakeEvalRedis.result = [0, 4]
        _FakeEvalRedis.raise_exc = None
        with patch.object(rl.redis, "Redis", _FakeEvalRedis):
            self.assertFalse(asyncio.run(rl.acquire_lease("t", "g", 4)))

    def test_acquire_lease_redis_dead_raises_unavailable(self):
        _FakeEvalRedis.raise_exc = ConnectionError("down")
        try:
            with patch.object(rl.redis, "Redis", _FakeEvalRedis):
                with self.assertRaises(LimiterUnavailable) as ctx:
                    asyncio.run(rl.acquire_lease("t", "g", 4))
        finally:
            _FakeEvalRedis.raise_exc = None
        self.assertEqual(ctx.exception.detail, "结构检索限流服务暂时不可用，请稍后重试")

    def test_structure_enter_lease_busy_raises_resource_busy_retry_5(self):
        async def ok(*a, **k):
            return None

        with patch.object(rl, "enforce", ok), \
                patch.object(rl, "acquire_lease", _lease_busy), \
                patch.object(rl, "structure_exit", _noop_exit):
            with self.assertRaises(ResourceBusy) as ctx:
                asyncio.run(rl.structure_enter(7))
        self.assertEqual(ctx.exception.detail, "结构检索并发已达上限，请稍后重试")
        self.assertEqual(ctx.exception.retry_after, 5)

    def test_structure_enter_global_dead_releases_actor_lease(self):
        """global lease Redis 故障 → actor 租约立即释放 + LimiterUnavailable。"""
        events: list = []

        async def ok(*a, **k):
            return None

        async def lease(bucket, identity, limit, ttl_seconds=30):
            # acquire_lease 内部的 Redis→neutral 转换被 patch 绕过,
            # 因此这里直接抛 acquire_lease 对外会抛的 neutral 异常,
            # 验证 structure_enter 的"释放已持 actor 租约"分支。
            if identity == "actor:7":
                return True
            raise LimiterUnavailable("结构检索限流服务暂时不可用，请稍后重试")

        async def fake_exit(held, bucket="structure-search"):
            events.append(tuple(held or []))

        with patch.object(rl, "enforce", ok), \
                patch.object(rl, "acquire_lease", lease), \
                patch.object(rl, "structure_exit", fake_exit):
            with self.assertRaises(LimiterUnavailable):
                asyncio.run(rl.structure_enter(7))
        self.assertIn(("actor:7",), events, "global 故障时必须立即释放 actor 租约")

    def test_release_best_effort_swallows(self):
        _FakeEvalRedis.raise_exc = ConnectionError("down")
        try:
            with patch.object(rl.redis, "Redis", _FakeEvalRedis):
                asyncio.run(rl.structure_exit(["a", "b"]))  # 不抛即通过
        finally:
            _FakeEvalRedis.raise_exc = None


class HttpBridgeTests(unittest.TestCase):
    def test_ratelimited_maps_429_with_headers(self):
        from api.rate_limit_http import to_http_exception
        exc = to_http_exception(RateLimited("请求过于频繁，请稍后重试", retry_after=30))
        self.assertEqual(exc.status_code, 429)
        self.assertEqual(exc.detail, "请求过于频繁，请稍后重试")
        self.assertEqual(exc.headers["Retry-After"], "30")
        self.assertEqual(exc.headers["X-RateLimit-Remaining"], "0")

    def test_limiter_unavailable_maps_503_no_headers(self):
        from api.rate_limit_http import to_http_exception
        exc = to_http_exception(LimiterUnavailable("限速服务暂时不可用，请稍后重试"))
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(exc.detail, "限速服务暂时不可用，请稍后重试")
        self.assertIsNone(exc.headers)

    def test_resource_busy_maps_429_retry_5_no_x_header(self):
        from api.rate_limit_http import to_http_exception
        exc = to_http_exception(ResourceBusy("结构检索并发已达上限，请稍后重试", retry_after=5))
        self.assertEqual(exc.status_code, 429)
        self.assertEqual(exc.headers["Retry-After"], "5")
        self.assertNotIn("X-RateLimit-Remaining", exc.headers or {})

    def test_enforce_http_passthrough_mapping(self):
        from fastapi import HTTPException
        from api.rate_limit_http import enforce_http

        async def _raise_ratelimited(*_a, **_k):
            raise RateLimited("请求过于频繁，请稍后重试", retry_after=12)

        with patch.object(rl, "enforce", _raise_ratelimited):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(enforce_http("t", "u", 10, 60))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)

    def test_structure_enter_http_maps(self):
        from fastapi import HTTPException
        from api.rate_limit_http import structure_enter_http

        async def ok(*a, **k):
            return None

        with patch.object(rl, "enforce", ok), patch.object(rl, "acquire_lease", _lease_busy):
            with patch.object(rl, "structure_exit", _noop_exit):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(structure_enter_http(7))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "5")


if __name__ == "__main__":
    unittest.main()
