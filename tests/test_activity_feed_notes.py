"""I-007 — 动态(activity feed)加入公开笔记, 针对性测试。

覆盖:
1. 公开发布通知关注者(创建即公开), note_id/note_excerpt 口径正确;
   混合流中 new_reaction 条目两字段为 null;
2. 私有转公开只通知一次(dedupe); 一直公开的编辑不重复通知;
3. 删除/改回私有后从列表与未读数消失(删除走 FK CASCADE);
4. 未读数 == 列表里未读的条数(与 dashboard 同一过滤);
5. 通知早于关注时间的事件不可见(与反应口径一致)。

直调 service/endpoint 函数 + 真链测试库; note 写限流走真实 redis。
"""
from __future__ import annotations

import re
import unittest
import uuid
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

from api.services import notes as notes_svc


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class ActivityFeedNoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        async with self.engine.begin() as conn:
            self.author = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x','Author') RETURNING id
            """), {
                "u": f"afn_a_{self.tag}", "e": f"afn_a_{self.tag}@example.test",
            })).scalar_one())
            self.follower = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x','Follower') RETURNING id
            """), {
                "u": f"afn_f_{self.tag}", "e": f"afn_f_{self.tag}@example.test",
            })).scalar_one())

    async def asyncTearDown(self):
        # users 删除级联: notes(owner) → notifications(note_id) 与
        # notifications(user_id/actor_user_id)、user_follows 全部随行消失。
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM community.users WHERE id IN (:a,:f)"),
                {"a": self.author, "f": self.follower},
            )
        await self.engine.dispose()

    async def _follow(self, *, follower: int | None = None) -> None:
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO community.user_follows(follower_user_id,followed_user_id)
                VALUES (:f,:a) ON CONFLICT DO NOTHING
            """), {"f": follower or self.follower, "a": self.author})
            await db.commit()

    async def _create_note(self, visibility: str, content: str) -> int:
        result = await notes_svc.create_note(
            self.Session(), actor_id=self.author, visibility=visibility,
            content=content, chemical_ids=[], reaction_ids=[],
        )
        return int(result["id"])

    async def _update_note(self, note_id: int, visibility: str, content: str) -> None:
        await notes_svc.update_note(
            self.Session(), note_id=note_id, actor_id=self.author,
            visibility=visibility, content=content,
            chemical_ids=[], reaction_ids=[],
        )

    async def _feed(self, user_id: int | None = None) -> dict:
        from api.social import notifications
        from api.core.security import Actor

        actor = Actor(
            user_id or self.follower, "u", "U", "u@t.example", "member",
            None, "session",
        )
        async with self.Session() as db:
            return await notifications(page=1, page_size=50, actor=actor, db=db)

    async def _unread(self, user_id: int | None = None) -> int:
        from api.social import unread_activity_count
        async with self.Session() as db:
            return await unread_activity_count(db, user_id or self.follower)

    async def _dashboard_unread(self) -> int:
        from api.users import dashboard_summary
        from api.core.security import Actor

        actor = Actor(
            self.follower, "u", "U", "u@t.example", "member", None, "session",
        )
        async with self.Session() as db:
            return (await dashboard_summary(actor=actor, db=db))["counts"]["unread"]

    async def test_public_note_notifies_follower_with_contract_fields(self):
        await self._follow()
        note_id = await self._create_note("public", "第一行: 苯甲酸重结晶\n第二行: 略")

        feed = await self._feed()
        self.assertEqual(len(feed["items"]), 1)
        item = feed["items"][0]
        self.assertEqual(item["event_type"], "new_note")
        self.assertEqual(item["note_id"], note_id)
        self.assertEqual(item["note_excerpt"], "第一行: 苯甲酸重结晶")
        self.assertIsNone(item["read_at"])
        self.assertEqual(await self._unread(), 1)
        self.assertEqual(await self._dashboard_unread(), 1)

        # 混入一条 new_reaction 通知: 反应类事件 note_id/note_excerpt 均为 null
        async with self.Session() as db:
            rid = int((await db.execute(text("""
                INSERT INTO chemistry.reactions
                  (reaction_smiles,reaction,created_by_user_id,visibility,source_type)
                VALUES ('C>>C', CAST('C>>C' AS public.reaction), :author, 'public', 'other')
                RETURNING id
            """), {"author": self.author})).scalar_one())
            await notes_svc.notify_new_note(db, self.author, note_id)  # 幂等不增
            from api.services.reactions import notify_new_reaction_safely
            await notify_new_reaction_safely(db, self.author, rid)

        feed = await self._feed()
        by_type = {item["event_type"]: item for item in feed["items"]}
        self.assertEqual(set(by_type), {"new_note", "new_reaction"})
        reaction_item = by_type["new_reaction"]
        self.assertIsNone(reaction_item["note_id"])
        self.assertIsNone(reaction_item["note_excerpt"])
        self.assertEqual(await self._unread(), 2)

        # 清理: reaction 删除会经 FK CASCADE 带走其 new_reaction 通知行
        async with self.Session() as db:
            await db.execute(text(
                "DELETE FROM chemistry.reactions WHERE id=:r"), {"r": rid})
            await db.commit()
        self.assertEqual(await self._unread(), 1)

    async def test_private_to_public_notifies_exactly_once(self):
        await self._follow()
        note_id = await self._create_note("private", "私人草稿")
        self.assertEqual(len((await self._feed())["items"]), 0)

        await self._update_note(note_id, "public", "公开了")
        self.assertEqual(len((await self._feed())["items"]), 1)

        # 一直公开的内容编辑: 不重复通知
        await self._update_note(note_id, "public", "公开了, 改了内容")
        self.assertEqual(len((await self._feed())["items"]), 1)

        # 私有 → 公开 → 私有 → 公开: dedupe_key 挡住第二次
        await self._update_note(note_id, "private", "又私有")
        self.assertEqual(len((await self._feed())["items"]), 0)
        await self._update_note(note_id, "public", "又公开")
        feed = (await self._feed())["items"]
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["note_id"], note_id)

    async def test_delete_and_reprivatize_remove_from_feed_and_unread(self):
        await self._follow()
        note_id = await self._create_note("public", "将被删除的笔记")
        self.assertEqual(await self._unread(), 1)

        # 改回私有: 列表与未读数立刻消失
        await self._update_note(note_id, "private", "将被删除的笔记")
        self.assertEqual(len((await self._feed())["items"]), 0)
        self.assertEqual(await self._unread(), 0)

        # 再公开后删除: 通知行被 FK CASCADE 物理删除
        await self._update_note(note_id, "public", "将被删除的笔记")
        self.assertEqual(await self._unread(), 1)
        async with self.Session() as db:
            await notes_svc.delete_note(db, note_id=note_id, actor_id=self.author)
        self.assertEqual(len((await self._feed())["items"]), 0)
        self.assertEqual(await self._unread(), 0)
        self.assertEqual(await self._dashboard_unread(), 0)

    async def test_unread_count_matches_feed_items(self):
        await self._follow()
        await self._create_note("public", "笔记 A")
        await self._create_note("public", "笔记 B")
        feed = (await self._feed())["items"]
        self.assertEqual(len(feed), 2)
        self.assertEqual(await self._unread(), 2)
        self.assertEqual(await self._dashboard_unread(), 2)

        from api.social import read_notifications
        from api.core.security import Actor

        actor = Actor(
            self.follower, "u", "U", "u@t.example", "member", None, "session",
        )
        async with self.Session() as db:
            await read_notifications(actor=actor, db=db)
        self.assertEqual(await self._unread(), 0)
        self.assertEqual(
            sum(1 for item in (await self._feed())["items"] if item["read_at"] is None),
            0,
        )

    async def test_note_older_than_follow_is_hidden(self):
        # 先发公开笔记, follower 之后才关注 → 不可见(与反应口径一致)
        await self._create_note("public", "关注我之前发的")
        await self._follow()
        self.assertEqual(len((await self._feed())["items"]), 0)
        self.assertEqual(await self._unread(), 0)


if __name__ == "__main__":
    unittest.main()
