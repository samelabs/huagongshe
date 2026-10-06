"""D001 — update_reaction 返回体契约回归测试(E3 后 owner 在 application service)。

锁:
- 成功更新(visibility 变或不变)必须返回同一 reaction_response payload;
  此前 visibility 未变分支 fall-through 返回 None(200 null)。
- visibility 副作用(notify 仅 private→public)、单次 commit、owner 前置。

E3 变更: 行锁/owner 规则/参与者替换/统计/事务/通知下沉
services.reactions.update_reaction。本文件打桩目标随之从 adapter 模块迁移到
service 模块(adapter 内已无 SQL/事务可打桩), 但**调用仍走 adapter**
(api.reactions.update_reaction), 因此 HTTP 映射契约继续被覆盖。
"""

from __future__ import annotations

import inspect
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import HTTPException

from api import reactions as reactions_module
from api.services import reactions as reactions_service


class FakeRow:
    def __init__(self, *vals):
        self._vals = list(vals)

    def __getitem__(self, i):
        return self._vals[i]


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeActor:
    def __init__(self, user_id=7, auth_kind="session"):
        self.id = user_id
        self.auth_kind = auth_kind


class FakeBody:
    def __init__(self, visibility):
        self.visibility = visibility


class _Base(unittest.IsolatedAsyncioTestCase):
    def _make_env(self, current_visibility="public", new_visibility="public",
                  owner=7):
        events = []

        class DB:
            def __init__(self):
                self.commit_count = 0
                self.rollback_count = 0

            async def execute(self, sql, params=None):
                sql_s = str(sql)
                if "FOR UPDATE" in sql_s:
                    return FakeResult(FakeRow(owner, current_visibility, "visible"))
                events.append(("execute", " ".join(sql_s.split())[:32]))
                return FakeResult(None)

            async def commit(self):
                events.append(("commit",))
                self.commit_count += 1

            async def rollback(self):
                events.append(("rollback",))
                self.rollback_count += 1

        return DB(), FakeActor(), FakeBody(new_visibility), events

    def _patched(self, events, new="public", notify_calls=None):
        """E3: 打桩目标 = service 模块(adapter 已无 SQL/事务可打桩)。"""

        def _notify(*a, **k):
            events.append(("notify",))
            if notify_calls is not None:
                notify_calls.append(a)
            return _async_none()

        stack = ExitStack()
        stack.enter_context(patch.object(reactions_service, "enforce",
                                         lambda *a, **k: _async_none()))
        stack.enter_context(patch.object(reactions_service, "canonical_participants",
                                         lambda b: ([], "C>O")))
        stack.enter_context(patch.object(reactions_service, "resolve_participants",
                                         lambda d, p: _async_pair([], [])))
        stack.enter_context(patch.object(reactions_service, "reaction_values",
                                         lambda b: {"visibility": b.visibility}))
        stack.enter_context(patch.object(
            reactions_service, "reaction_response",
            lambda d, rid, cc: _async_ret({"id": 5, "visibility": new})))
        stack.enter_context(patch.object(reactions_service,
                                         "notify_new_reaction_safely", _notify))
        return stack

    async def _run(self, current="public", new="public", owner=7,
                   actor_id=7, auth_kind="session"):
        db, actor, body, events = self._make_env(current, new, owner=owner)
        actor.id = actor_id
        actor.auth_kind = auth_kind
        with self._patched(events, new=new):
            result = await reactions_module.update_reaction(
                body=body, reaction_id=5, actor=actor, db=db)
        return result, events, db


class UpdateReactionReturnTests(_Base):
    async def test_case1_visibility_unchanged_returns_payload(self):
        """D001 核心: visibility 未变(public→public)也返回 payload。"""
        result, events, db = await self._run(current="public", new="public")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 5)
        self.assertEqual(events.count(("commit",)), 1)
        self.assertEqual(db.rollback_count, 0)

    async def test_case2_private_to_public_returns_payload(self):
        result, _, _ = await self._run(current="private", new="public")
        self.assertIsNotNone(result)
        self.assertEqual(result["visibility"], "public")

    async def test_case3_public_to_private_returns_payload(self):
        result, _, _ = await self._run(current="public", new="private")
        self.assertIsNotNone(result)
        self.assertEqual(result["visibility"], "private")

    async def test_case6_single_commit_before_return(self):
        _, events, db = await self._run(current="public", new="public")
        self.assertEqual(db.commit_count, 1)  # commit 次数/时点不变
        self.assertEqual(events.count(("commit",)), 1)

    async def test_return_unconditional_in_source(self):
        src = inspect.getsource(reactions_service.update_reaction)
        self.assertNotIn("if current[1] != body.visibility:", src)
        self.assertIn("return await reaction_response", src)

    async def test_case5_owner_gate_before_row_fetch(self):
        """E3: owner 前置不变, 但 owner 现在是 service(源码结构锁)。

        service: agent 403 → FOR UPDATE → owner 检查 → canonical kernel;
        adapter: 零行锁/零 SQL(不得留半迁移)。
        """
        svc = inspect.getsource(reactions_service.update_reaction)
        self.assertIn('auth_kind in ("agent", "oauth")', svc)
        self.assertIn("FOR UPDATE", svc)
        self.assertIn("只能维护自己创建的反应", svc)
        self.assertLess(svc.index("FOR UPDATE"),
                        svc.index("只能维护自己创建的反应"))
        self.assertLess(svc.index("只能维护自己创建的反应"),
                        svc.index("canonical_participants"))
        adapter = inspect.getsource(reactions_module.update_reaction)
        self.assertNotIn("FOR UPDATE", adapter)
        self.assertNotIn("UPDATE chemistry.reactions", adapter)
        self.assertNotIn("commit", adapter)

    async def test_unauthorized_update_is_403_and_rollback(self):
        """非 owner: adapter 403 + 原文 detail; service rollback, 未 commit。"""
        db, actor, body, events = self._make_env(owner=7)
        actor.id = 8
        with self._patched(events):
            with self.assertRaises(HTTPException) as ctx:
                await reactions_module.update_reaction(
                    body=body, reaction_id=5, actor=actor, db=db)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "只能维护自己创建的反应")
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.rollback_count, 1)

    async def test_agent_edit_is_403_and_no_db_work(self):
        """agent(AI Key)编辑: 403 + 原文 detail(现由 service 中性错误产生)。"""
        db, actor, body, events = self._make_env()
        actor.auth_kind = "agent"
        with self._patched(events):
            with self.assertRaises(HTTPException) as ctx:
                await reactions_module.update_reaction(
                    body=body, reaction_id=5, actor=actor, db=db)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail,
                         "API Token 当前不开放反应编辑，请使用网页登录会话")
        self.assertEqual(events, [])  # agent 403 在任何 DB 动作之前

    async def test_notify_only_on_public_transition(self):
        """visibility 副作用保持: 仅 private→public 触发 notify, 且在 commit 后。"""
        for current, new, expected in (("private", "public", 1),
                                       ("public", "public", 0),
                                       ("public", "private", 0)):
            calls = []
            db, actor, body, events = self._make_env(current, new)
            with self._patched(events, new=new, notify_calls=calls):
                await reactions_module.update_reaction(
                    body=body, reaction_id=5, actor=actor, db=db)
            self.assertEqual(len(calls), expected, f"{current}->{new}")
            self.assertEqual(events.count(("notify",)), expected)
            if expected:
                self.assertGreater(events.index(("notify",)),
                                   events.index(("commit",)))


def _async_none():
    return _Awaitable(None)


def _async_ret(v):
    return _Awaitable(v)


def _async_pair(a, b):
    return _Awaitable((a, b))


class _Awaitable:
    def __init__(self, v):
        self._v = v

    def __await__(self):
        if False:
            yield
        return self._v


if __name__ == "__main__":
    unittest.main()
