"""D001 — update_reaction missing return 回归测试。

核心: 成功更新(visibility 变或不变)必须返回同一 reaction_response
payload; 此前 visibility 未变分支 fall-through 返回 None(200 null)。
事务/鉴权/可见性行为零变化。
"""

from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import patch

from api import reactions as reactions_module


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


class _Base(unittest.IsolatedAsyncioTestCase):
    def _make_env(self, current_visibility="public", new_visibility="public"):
        """构造 update_reaction 全链替身。

        返回 (db, actor, body, events)。body 为 ReactionBody 兼容替身。
        """
        events = []

        class DB:
            def __init__(self):
                self.commit_count = 0

            async def execute(self, sql, params=None):
                sql_s = str(sql)
                if "FOR UPDATE" in sql_s:
                    return FakeResult(
                        FakeRow(7, current_visibility, "visible"))
                events.append(("execute", sql_s[:40]))
                return FakeResult(None)

            async def commit(self):
                events.append(("commit",))
                self.commit_count += 1

        db = DB()

        class Actor:
            id = 7
            auth_kind = "session"
            role = "member"

        class Body:
            pass

        body = Body()
        body.visibility = new_visibility
        body.reaction = "C>O"
        # canonical_participants 在线程池内跑, 替身最小返回
        return db, Actor(), body, events

    async def _run(self, current="public", new="public"):
        db, actor, body, events = self._make_env(current, new)
        payload = {"id": 5, "visibility": new}
        with patch.object(reactions_module, "enforce_http",
                          lambda *a, **k: _async_none()), \
             patch.object(reactions_module, "canonical_participants",
                          lambda b: ([], "C>O")), \
             patch.object(reactions_module, "resolve_participants",
                          lambda d, p: _async_pair([], [])), \
             patch.object(reactions_module, "reaction_values",
                          lambda b: {"visibility": b.visibility}), \
             patch.object(reactions_module, "reaction_response",
                          lambda d, rid, cc: _async_ret(payload)), \
             patch.object(reactions_module, "notify_new_reaction_safely",
                          lambda *a, **k: _async_none()):
            result = await reactions_module.update_reaction(
                body=body, reaction_id=5, actor=actor, db=db)
        return result, events, db


class D001Tests(_Base):
    async def test_case1_visibility_changed_returns_payload(self):
        result, _, _ = await self._run(current="public", new="private")
        self.assertIsNotNone(result)
        self.assertEqual(result["visibility"], "private")

    async def test_case2_visibility_unchanged_returns_payload_not_none(self):
        # D001 核心: 未变分支此前 fall-through → None
        result, _, _ = await self._run(current="public", new="public")
        self.assertIsNotNone(result)
        self.assertEqual(result["visibility"], "public")

    async def test_case3_response_parity_between_branches(self):
        changed, _, _ = await self._run(current="private", new="public")
        unchanged, _, _ = await self._run(current="public", new="public")
        self.assertEqual(sorted(changed.keys()), sorted(unchanged.keys()))

    async def test_case4_updated_field_reflected(self):
        result, _, _ = await self._run(current="public", new="private")
        self.assertEqual(result["visibility"], "private")  # 新值

    async def test_case5_owner_gate_before_row_fetch(self):
        """owner≠actor 403 / agent 403 前置不变(源码结构锁)。"""
        src = inspect.getsource(reactions_module.update_reaction)
        self.assertIn('auth_kind == "agent"', src)
        self.assertIn("只能维护自己创建的反应", src)
        self.assertIn("FOR UPDATE", src)

    async def test_case6_single_commit_before_return(self):
        _, events, db = await self._run(current="public", new="public")
        self.assertEqual(db.commit_count, 1)  # commit 次数/时点不变
        self.assertEqual(events.count(("commit",)), 1)

    async def test_notify_only_on_public_transition(self):
        """visibility 副作用保持: 仅 private→public 触发 notify。"""
        calls = []
        with patch.object(reactions_module, "enforce_http",
                          lambda *a, **k: _async_none()), \
             patch.object(reactions_module, "canonical_participants",
                          lambda b: ([], "C>O")), \
             patch.object(reactions_module, "resolve_participants",
                          lambda d, p: _async_pair([], [])), \
             patch.object(reactions_module, "reaction_values",
                          lambda b: {"visibility": b.visibility}), \
             patch.object(reactions_module, "reaction_response",
                          lambda d, rid, cc: _async_ret({"id": 5})), \
             patch.object(reactions_module, "notify_new_reaction_safely",
                          lambda *a, **k: calls.append(a) or _async_none()):
            await self._run.__self__ if False else None
            db, actor, body, _ = self._make_env("private", "public")
            await reactions_module.update_reaction(
                body=body, reaction_id=5, actor=actor, db=db)
        self.assertEqual(len(calls), 1)
        # unchanged: 无 notify
        calls.clear()
        with patch.object(reactions_module, "enforce_http",
                          lambda *a, **k: _async_none()), \
             patch.object(reactions_module, "canonical_participants",
                          lambda b: ([], "C>O")), \
             patch.object(reactions_module, "resolve_participants",
                          lambda d, p: _async_pair([], [])), \
             patch.object(reactions_module, "reaction_values",
                          lambda b: {"visibility": b.visibility}), \
             patch.object(reactions_module, "reaction_response",
                          lambda d, rid, cc: _async_ret({"id": 5})), \
             patch.object(reactions_module, "notify_new_reaction_safely",
                          lambda *a, **k: calls.append(a) or _async_none()):
            db, actor, body, _ = self._make_env("public", "public")
            await reactions_module.update_reaction(
                body=body, reaction_id=5, actor=actor, db=db)
        self.assertEqual(len(calls), 0)

    async def test_return_unconditional_in_source(self):
        src = inspect.getsource(reactions_module.update_reaction)
        self.assertNotIn("if current[1] != body.visibility:", src)
        self.assertIn("return await reaction_response", src)


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
