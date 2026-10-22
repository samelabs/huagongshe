""" — GET/DELETE /users/me/oauth-connections 针对性测试。

覆盖:
1. 列表只含本人数据(跨用户同 client 隔离), 字段口径: scopes 并集 /
   authorized_at=最早有效 token / last_used_at=access 的 max / 倒序;
2. 撤销后: 列表消失, 已撤销 access token 走 MCP 鉴权链返回 invalid_token
   (401 语义), refresh 换 token 失败(invalid_grant);
3. 跨用户 DELETE 不影响他人同 client 的连接;
4. 重复 DELETE / 未知 client_id DELETE 均 204 幂等。

直调 endpoint 函数 + 真链测试库(与 test_token_revoke_idempotency 同法)。
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone
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
    assert parse_qs(_u.query).get("test_sentinel") in (["hgs-test-db"], ["hgs-ephemeral-db"])
    ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

from api.services import oauth as svc


class _Resp:
    headers: dict = {}

    def delete_cookie(self, *a, **k):
        pass


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class OauthConnectionsManageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        async with self.engine.begin() as conn:
            self.user_a = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x','A') RETURNING id
            """), {
                "u": f"ocm_a_{self.tag}", "e": f"ocm_a_{self.tag}@example.test",
            })).scalar_one())
            self.user_b = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x','B') RETURNING id
            """), {
                "u": f"ocm_b_{self.tag}", "e": f"ocm_b_{self.tag}@example.test",
            })).scalar_one())

        now = datetime.now(timezone.utc)
        self.t = {name: now - delta for name, delta in (
            ("t1", timedelta(hours=4)), ("t2", timedelta(hours=3)),
            ("t3", timedelta(hours=2)), ("t4", timedelta(hours=1)),
        )}
        self.resource = svc.mcp_resource_url()

        async with self.Session() as db:
            self.client_shared = (await svc.register_client(
                db,
                redirect_uris=["https://chatgpt.example.test/cb"],
                client_name="Shared Client",
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=None,
                application_type=None,
            ))["client_id"]
            self.client_unused = (await svc.register_client(
                db,
                redirect_uris=["https://claude.example.test/cb"],
                client_name="Unused Client",
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=None,
                application_type=None,
            ))["client_id"]
            self.client_dead = (await svc.register_client(
                db,
                redirect_uris=["https://dead.example.test/cb"],
                client_name="Dead Client",
                token_endpoint_auth_method="none",
                grant_types=None,
                response_types=None,
                application_type=None,
            ))["client_id"]

        # access/refresh 明文只在测试进程内存中持有, 落库的是 sha256 摘要。
        self.access_a = f"hgo_at_{uuid.uuid4().hex}"
        self.refresh_a = f"hgo_rt_{uuid.uuid4().hex}"
        self.access_a2 = f"hgo_at_{uuid.uuid4().hex}"
        self.access_b = f"hgo_at_{uuid.uuid4().hex}"
        async with self.engine.begin() as conn:
            # A + client_shared: 双 token, scopes 不同, 有 last_used_at(取最新 t4)。
            await conn.execute(text("""
                INSERT INTO community.oauth_access_tokens(
                    token_hash,user_id,client_id,scopes,resource,created_at,
                    expires_at,last_used_at)
                VALUES (:h,:uid,:cid,ARRAY['read'],:res,:c1,
                        now()+interval '1 hour',:t4)
            """), {
                "h": hashlib.sha256(self.access_a.encode()).digest(),
                "uid": self.user_a, "cid": self.client_shared,
                "res": self.resource, "c1": self.t["t1"], "t4": self.t["t4"],
            })
            await conn.execute(text("""
                INSERT INTO community.oauth_refresh_tokens(
                    token_hash,user_id,client_id,scopes,resource,created_at,
                    expires_at)
                VALUES (:h,:uid,:cid,ARRAY['reaction:write'],:res,:c2,
                        now()+interval '1 day')
            """), {
                "h": hashlib.sha256(self.refresh_a.encode()).digest(),
                "uid": self.user_a, "cid": self.client_shared,
                "res": self.resource, "c2": self.t["t2"],
            })
            # A + client_unused: 只有 access, 授权于最早的 t1, 从未用过。
            await conn.execute(text("""
                INSERT INTO community.oauth_access_tokens(
                    token_hash,user_id,client_id,scopes,resource,created_at,
                    expires_at)
                VALUES (:h,:uid,:cid,ARRAY['read'],:res,:c1,
                        now()+interval '1 hour')
            """), {
                "h": hashlib.sha256(self.access_a2.encode()).digest(),
                "uid": self.user_a, "cid": self.client_unused,
                "res": self.resource, "c1": self.t["t1"],
            })
            # B + client_shared: 同一 client 的他人连接。
            await conn.execute(text("""
                INSERT INTO community.oauth_access_tokens(
                    token_hash,user_id,client_id,scopes,resource,created_at,
                    expires_at)
                VALUES (:h,:uid,:cid,ARRAY['read'],:res,:t4,
                        now()+interval '1 hour')
            """), {
                "h": hashlib.sha256(self.access_b.encode()).digest(),
                "uid": self.user_b, "cid": self.client_shared,
                "res": self.resource, "t4": self.t["t4"],
            })
            # A + client_dead: 已撤销 access + 已过期 refresh → 不得出现在列表。
            await conn.execute(text("""
                INSERT INTO community.oauth_access_tokens(
                    token_hash,user_id,client_id,scopes,resource,created_at,
                    expires_at,revoked_at)
                VALUES (:h,:uid,:cid,ARRAY['read'],:res,now()-interval '2 hours',
                        now()+interval '1 hour',now()-interval '1 hour')
            """), {
                "h": hashlib.sha256(f"hgo_at_dead_{self.tag}".encode()).digest(),
                "uid": self.user_a, "cid": self.client_dead, "res": self.resource,
            })
            await conn.execute(text("""
                INSERT INTO community.oauth_refresh_tokens(
                    token_hash,user_id,client_id,scopes,resource,created_at,
                    expires_at)
                VALUES (:h,:uid,:cid,ARRAY['read'],:res,now()-interval '2 hours',
                        now()-interval '1 minute')
            """), {
                "h": hashlib.sha256(f"hgo_rt_dead_{self.tag}".encode()).digest(),
                "uid": self.user_a, "cid": self.client_dead, "res": self.resource,
            })

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM community.oauth_clients WHERE client_id LIKE 'hgo_client_%'")
            )
            await conn.execute(
                text("DELETE FROM community.users WHERE id IN (:a,:b)"),
                {"a": self.user_a, "b": self.user_b},
            )
        await self.engine.dispose()

    async def _list(self, user_id: int) -> dict:
        from api.users import list_oauth_connections
        from api.core.security import Actor

        actor = Actor(
            user_id, f"u{user_id}", "U", f"u{user_id}@t.example", "member",
            None, "session",
        )
        async with self.Session() as db:
            return await list_oauth_connections(
                response=_Resp(), actor=actor, db=db)

    async def _revoke(self, user_id: int, client_id: str) -> None:
        from api.users import revoke_oauth_connection
        from api.core.security import Actor

        actor = Actor(
            user_id, f"u{user_id}", "U", f"u{user_id}@t.example", "member",
            None, "session",
        )
        async with self.Session() as db:
            await revoke_oauth_connection(client_id=client_id, actor=actor, db=db)

    async def test_list_only_own_data_with_contract_fields(self):
        result = await self._list(self.user_a)
        by_client = {item["client_id"]: item for item in result["items"]}
        self.assertEqual(
            set(by_client), {self.client_shared, self.client_unused},
            "列表必须只含本人仍有有效 token 的 client(排除他人与已死 token)",
        )

        shared = by_client[self.client_shared]
        self.assertEqual(shared["client_name"], "Shared Client")
        # scopes = 有效 token 的并集(顺序非契约点)
        self.assertEqual(set(shared["scopes"]), {"read", "reaction:write"})
        self.assertEqual(shared["authorized_at"], self.t["t1"])
        self.assertEqual(shared["last_used_at"], self.t["t4"])

        unused = by_client[self.client_unused]
        self.assertIsNone(unused["last_used_at"])
        self.assertEqual(unused["authorized_at"], self.t["t1"])

        # 倒序: last_used_at(t4) 在前; 无使用记录的按 authorized_at(t1) 排后。
        self.assertEqual(
            [item["client_id"] for item in result["items"]],
            [self.client_shared, self.client_unused],
        )

        # 同一 client, B 的列表只看到自己。
        result_b = await self._list(self.user_b)
        self.assertEqual(
            [item["client_id"] for item in result_b["items"]],
            [self.client_shared],
        )

    async def test_revoke_removes_connection_and_kills_tokens(self):
        from api import mcp_server

        await self._revoke(self.user_a, self.client_shared)

        result = await self._list(self.user_a)
        self.assertEqual(
            [item["client_id"] for item in result["items"]],
            [self.client_unused],
            "撤销后该 client 应从列表消失",
        )

        # access token 立即失效: MCP 鉴权链返回 invalid_token(401 语义)。
        headers = {"authorization": f"Bearer {self.access_a}"}
        with patch.object(
            mcp_server, "async_session",
            new=lambda: self.Session(),
        ):
            actor, challenge = await mcp_server._require_tool_actor(
                headers, oauth_scope="read", agent_scope=None)
        self.assertIsNone(actor)
        self.assertIsNotNone(challenge)
        self.assertTrue(challenge.is_error)
        www_auth = (challenge.meta or {}).get("mcp/www_authenticate") or []
        self.assertIn('error="invalid_token"', www_auth[0])

        async with self.Session() as db:
            self.assertIsNone(await svc.resolve_access_token(
                db, self.access_a, expected_resource=self.resource))

        # refresh token 同时失效: 换新 token 必须失败。
        with self.assertRaises(svc.OAuthProtocolError) as raised:
            async with self.Session() as db:
                await svc.refresh_access_token(
                    db,
                    client_id=self.client_shared,
                    refresh_token=self.refresh_a,
                    scope=None,
                    resource=self.resource,
                )
        self.assertEqual(raised.exception.error, "invalid_grant")

    async def test_cross_user_revoke_leaves_other_user_intact(self):
        from api import mcp_server

        await self._revoke(self.user_a, self.client_shared)

        result_b = await self._list(self.user_b)
        self.assertEqual(
            [item["client_id"] for item in result_b["items"]],
            [self.client_shared],
            "A 撤销不得影响 B 对同一 client 的授权",
        )
        headers = {"authorization": f"Bearer {self.access_b}"}
        with patch.object(
            mcp_server, "async_session", new=lambda: self.Session(),
        ):
            actor, challenge = await mcp_server._require_tool_actor(
                headers, oauth_scope="read", agent_scope=None)
        self.assertIsNotNone(actor, "B 的 access token 必须仍然可用")
        self.assertIsNone(challenge)

    async def test_disconnect_waits_for_refresh_and_revokes_new_pair(self):
        ready, release = asyncio.Event(), asyncio.Event()
        issuing = svc._issue_token_pair
        async def held_issue(*args, **kwargs):
            result = await issuing(*args, **kwargs)
            ready.set()
            await release.wait()
            return result
        async def refresh():
            async with self.Session() as db:
                return await svc.refresh_access_token(db, client_id=self.client_shared,
                    refresh_token=self.refresh_a, scope=None, resource=self.resource)
        pid = asyncio.Queue()
        async def revoke():
            async with self.Session() as db:
                await pid.put((await db.execute(text("SELECT pg_backend_pid()"))).scalar_one())
                await svc.revoke_connection(db, user_id=self.user_a, client_id=self.client_shared)
        with patch.object(svc, "_issue_token_pair", held_issue):
            first = asyncio.create_task(refresh())
            second = None
            try:
                await asyncio.wait_for(ready.wait(), 5)
                second = asyncio.create_task(revoke())
                backend = await asyncio.wait_for(pid.get(), 5)
                async with self.engine.connect() as observer:
                    async def wait_blocked():
                        while not (await observer.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": backend})).scalar_one():
                            if second.done():
                                self.fail("revoke did not wait for the issuing transaction")
                            await asyncio.sleep(0.01)
                    await asyncio.wait_for(wait_blocked(), 5)
            finally:
                release.set()
                results = await asyncio.wait_for(asyncio.gather(first, *([second] if second else [])), 5)
        async with self.Session() as db:
            self.assertIsNone(await svc.resolve_access_token(db, results[0]["access_token"], expected_resource=self.resource))
            with self.assertRaises(svc.OAuthProtocolError):
                await svc.refresh_access_token(db, client_id=self.client_shared,
                    refresh_token=results[0]["refresh_token"], scope=None, resource=self.resource)

    async def test_repeated_and_unknown_revoke_are_idempotent_204(self):
        # 重复撤销与未知 client_id 都走 204 路径: 直调无异常即代表 204。
        await self._revoke(self.user_a, self.client_shared)
        await self._revoke(self.user_a, self.client_shared)
        await self._revoke(self.user_a, "hgo_client_does_not_exist")

        # 幂等撤销不误伤他人。
        result_b = await self._list(self.user_b)
        self.assertEqual(
            [item["client_id"] for item in result_b["items"]],
            [self.client_shared],
        )

    async def test_agent_token_cannot_list_connections(self):
        """ 收紧: 凭据管理只认网页会话, AI Key(agent)调用 403。"""
        import inspect

        from fastapi import HTTPException

        from api.core.security import Actor, current_session
        from api.users import list_oauth_connections

        # 依赖语义: agent actor 过不了 current_session(与 /users/me/tokens 一致)
        agent_actor = Actor(
            self.user_a, "u", "U", "u@t.example", "member", None,
            "agent", 99, ("read",),
        )
        with self.assertRaises(HTTPException) as raised:
            await current_session(agent_actor)
        self.assertEqual(raised.exception.status_code, 403)

        # 端点签名确实绑定 current_session(防回退到 current_actor)
        source = inspect.getsource(list_oauth_connections)
        self.assertIn("Depends(current_session)", source)


if __name__ == "__main__":
    unittest.main()
