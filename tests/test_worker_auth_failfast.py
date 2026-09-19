"""R4.1 1: worker WorkAPI 鉴权 fail-fast 回归锁。

- 401/403 → WorkApiHTTPError(fatal_auth) 穿出 loop, 进程非零退出
- 网络/timeout/5xx/409 保持 transient(不升级、不退出)
- auth preflight: capabilities=[] 零领取; 401 → SystemExit(2)
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.main import (  # noqa: E402
    WorkApiClient, WorkApiHTTPError, _auth_preflight, _cb_loop, _identity_loop,
    _pb_loop, _reraise_fatal_auth,
)


class FakeResp:
    def __init__(self, status: int, body: bytes = b"{}"):
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakePost:
    """session.post(...) 返回 async context manager(非 coroutine)。"""

    def __init__(self, resp: FakeResp):
        self.resp = resp
        self.args = None
        self.kwargs = None

    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        return self

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *a):
        return False


def _client(status: int, detail: bytes = b'{"detail":"unknown or disabled worker"}'):
    sess = mock.AsyncMock()
    fp = FakePost(FakeResp(status, detail))
    sess.post = fp
    return WorkApiClient(sess, "http://127.0.0.1:8000", "w1", "t"), fp


class ExceptionTypingTests(unittest.TestCase):
    def test_401_is_fatal_auth_with_status_and_detail(self):
        c, _ = _client(401)
        with self.assertRaises(WorkApiHTTPError) as cm:
            asyncio.run(c.post("/workapi/v1/jobs/lease", {}))
        self.assertEqual(cm.exception.status, 401)
        self.assertIn("unknown or disabled worker", cm.exception.detail)
        self.assertTrue(cm.exception.fatal_auth)

    def test_403_is_fatal_auth(self):
        c, _ = _client(403, b"forbidden")
        with self.assertRaises(WorkApiHTTPError) as cm:
            asyncio.run(c.post("/x", {}))
        self.assertTrue(cm.exception.fatal_auth)

    def test_409_business_state_not_auth(self):
        c, _ = _client(409, b"lease conflict")
        with self.assertRaises(WorkApiHTTPError) as cm:
            asyncio.run(c.post("/x", {}))
        self.assertFalse(cm.exception.fatal_auth)

    def test_500_transient_not_auth(self):
        c, _ = _client(500, b"boom")
        with self.assertRaises(WorkApiHTTPError) as cm:
            asyncio.run(c.post("/x", {}))
        self.assertFalse(cm.exception.fatal_auth)


class LoopNotSwallowAuthTests(unittest.TestCase):
    """lease 401 → loop 边界必须上抛而非 sleep-retry。"""

    def _loop_raises(self, coro_factory) -> None:
        c, _ = _client(401)
        with self.assertRaises(WorkApiHTTPError):
            asyncio.run(asyncio.wait_for(coro_factory(c), timeout=3))

    def test_pb_loop_raises_on_401(self):
        sess = mock.AsyncMock()
        rate = mock.AsyncMock()
        self._loop_raises(
            lambda c: _pb_loop(c, sess, rate, 1))

    def test_cb_loop_raises_on_401(self):
        sess = mock.AsyncMock()
        rate = mock.AsyncMock()
        self._loop_raises(
            lambda c: _cb_loop(c, sess, rate))

    def test_identity_loop_raises_on_401(self):
        sess = mock.AsyncMock()
        rate = mock.AsyncMock()
        self._loop_raises(
            lambda c: _identity_loop(c, sess, rate))

    def test_reraise_guard_passthrough(self):
        e = WorkApiHTTPError(401, "x")
        with self.assertRaises(WorkApiHTTPError):
            _reraise_fatal_auth(e)
        _reraise_fatal_auth(RuntimeError("transient"))  # 不抛
        _reraise_fatal_auth(WorkApiHTTPError(409, "conflict"))  # 不抛


class AuthPreflightTests(unittest.TestCase):
    def test_preflight_ok_zero_jobs(self):
        c, fp = _client(200, b'{"jobs":[]}')

        async def go():
            await _auth_preflight(c, ["pubchem", "cas"])

        asyncio.run(go())
        # 验证请求体: capabilities=[] 零领取副作用
        body = fp.kwargs.get("data")
        self.assertIn(b'"capabilities":[]', body)

    def test_preflight_401_nonzero_exit(self):
        c, _ = _client(401)
        with self.assertRaises(SystemExit) as cm:
            asyncio.run(_auth_preflight(c, ["pubchem"]))
        self.assertEqual(cm.exception.code, 2)

    def test_preflight_403_nonzero_exit(self):
        c, _ = _client(403)
        with self.assertRaises(SystemExit):
            asyncio.run(_auth_preflight(c, ["cas"]))

    def test_preflight_cas_scope_uses_cas_lease(self):
        c, fp = _client(200, b'{"jobs":[]}')
        asyncio.run(_auth_preflight(c, ["cas"]))
        self.assertIn("/workapi/v1/cas/jobs/lease", fp.args[0])

    def test_preflight_no_scopes_exits(self):
        c, _ = _client(200)
        with self.assertRaises(SystemExit):
            asyncio.run(_auth_preflight(c, []))

    def test_preflight_unexpected_jobs_aborts(self):
        c, _ = _client(200, b'{"jobs":[{"job_id":"j1"}]}')
        with self.assertRaises(SystemExit):
            asyncio.run(_auth_preflight(c, ["pubchem"]))


if __name__ == "__main__":
    unittest.main()
