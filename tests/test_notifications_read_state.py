""" — 通知已读/未读状态链路（原子化通知模块读取侧）。

覆盖（owner = api/services/notifications.py，端点层只做 HTTP 映射）:
1. 单条已读: 只影响目标行, 未读数同步减一, 列表 read_at 口径一致;
   重复读幂等（仍成功, 未读数不变）。
2. 所有权: 他人通知/不存在 id → mark_read False → 端点 404。
3. 全量已读: 含动态流不可见的残留行（隐藏行不再挂未读）。
4. 不变量: 未读数 == 列表里未读的条数（部分已读后仍成立）。
5. 写入侧经 owner 扇出（follow → new_follower 直达收件人）。
6. 端点接线: 关注用户 → new_follower、收藏公开反应 → reaction_favorited
   （重复关注/取关再关注不重复打扰; 无作者的导入反应无人可通知）。

直调 service/endpoint 函数 + 真链测试库。
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

from api.services import notifications as notifications_svc
from api.services.notes import create_note


def _actor(user_id: int):
    from api.core.security import Actor
    return Actor(user_id, "u", "U", "u@t.example", "member", None, "session")


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class NotificationReadStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        self.reaction_ids: list[int] = []
        async with self.engine.begin() as conn:
            ids = (await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:a,:ae,'x','Author'),(:f,:fe,'x','Follower')
                RETURNING id
            """), {
                "a": f"nrs_a_{self.tag}", "ae": f"nrs_a_{self.tag}@example.test",
                "f": f"nrs_f_{self.tag}", "fe": f"nrs_f_{self.tag}@example.test",
            })).scalars().all()
            self.author, self.follower = int(ids[0]), int(ids[1])
            await conn.execute(text("""
                INSERT INTO community.user_follows(follower_user_id,followed_user_id)
                VALUES (:f,:a)
            """), {"f": self.follower, "a": self.author})

    async def asyncTearDown(self):
        # users 删除级联: notes → notifications(note_id) 与
        # notifications(user_id/actor_user_id)、user_follows 全部随行消失。
        async with self.engine.begin() as conn:
            # reactions.created_by_user_id 为 ON DELETE RESTRICT: 先删反应夹具
            if self.reaction_ids:
                await conn.execute(
                    text("DELETE FROM chemistry.reactions WHERE id = ANY(:ids)"),
                    {"ids": self.reaction_ids},
                )
            await conn.execute(
                text("DELETE FROM community.users WHERE id IN (:a,:f)"),
                {"a": self.author, "f": self.follower},
            )
        await self.engine.dispose()

    async def _notify_two_notes(self) -> tuple[int, int]:
        """作者连发两条公开笔记 → 关注者收件箱两条 new_note。"""
        ids = []
        for i in range(2):
            async with self.Session() as db:
                result = await create_note(
                    db, actor_id=self.author, visibility="public",
                    content=f"第{i}条: 重结晶", chemical_ids=[], reaction_ids=[],
                )
                ids.append(int(result["id"]))
        return ids[0], ids[1]

    async def _feed(self, user_id: int | None = None) -> dict:
        from api.social import notifications
        async with self.Session() as db:
            return await notifications(
                page=1, page_size=50, actor=_actor(user_id or self.follower), db=db)

    async def _unread(self, user_id: int | None = None) -> int:
        async with self.Session() as db:
            return await notifications_svc.unread_count(db, user_id or self.follower)

    async def _insert_reaction(self, owner: int | None) -> int:
        async with self.engine.begin() as conn:
            rid = int((await conn.execute(text("""
                INSERT INTO chemistry.reactions(
                    created_by_user_id,visibility,moderation_status,created_via,source_type
                ) VALUES (:owner,'public','visible','web','self')
                RETURNING id
            """), {"owner": owner})).scalar_one())
        self.reaction_ids.append(rid)
        return rid

    async def test_single_read_marks_only_target_row(self):
        await self._notify_two_notes()
        feed = await self._feed()
        self.assertEqual(len(feed["items"]), 2)
        target = feed["items"][0]["id"]  # 较新一条
        self.assertEqual(await self._unread(), 2)

        async with self.Session() as db:
            marked = await notifications_svc.mark_read(db, self.follower, target)
            self.assertTrue(marked)
            await db.commit()

        feed = await self._feed()
        by_id = {item["id"]: item for item in feed["items"]}
        self.assertIsNotNone(by_id[target]["read_at"])
        other = next(i["id"] for i in feed["items"] if i["id"] != target)
        self.assertIsNone(by_id[other]["read_at"])
        # 不变量: 未读数 == 列表里未读的条数
        self.assertEqual(await self._unread(), 1)
        self.assertEqual(
            sum(1 for i in feed["items"] if i["read_at"] is None), await self._unread(),
        )

    async def test_single_read_is_idempotent(self):
        await self._notify_two_notes()
        feed = await self._feed()
        target = feed["items"][0]["id"]
        async with self.Session() as db:
            self.assertTrue(await notifications_svc.mark_read(db, self.follower, target))
            await db.commit()
        before = await self._unread()
        async with self.Session() as db:
            self.assertTrue(await notifications_svc.mark_read(db, self.follower, target))
            await db.commit()
        self.assertEqual(await self._unread(), before)

    async def test_read_endpoint_ownership_and_not_found(self):
        from fastapi import HTTPException
        from api.social import read_notification

        await self._notify_two_notes()
        feed = await self._feed()
        target = feed["items"][0]["id"]

        # 他人通知 → 404（作者并非收件人）
        async with self.Session() as db:
            with self.assertRaises(HTTPException) as ctx:
                await read_notification(
                    notification_id=target, actor=_actor(self.author), db=db,
                )
            self.assertEqual(ctx.exception.status_code, 404)

        # 不存在的 id → 404
        async with self.Session() as db:
            with self.assertRaises(HTTPException):
                await read_notification(
                    notification_id=2_000_000_000, actor=_actor(self.follower), db=db,
                )

        # 收件人本人 → 204（无返回值）
        async with self.Session() as db:
            self.assertIsNone(await read_notification(
                notification_id=target, actor=_actor(self.follower), db=db,
            ))
        self.assertEqual(await self._unread(), 1)

    async def test_mark_all_read_covers_rows_hidden_from_feed(self):
        await self._notify_two_notes()
        # 作者把其中一条笔记转回私有 → 该通知从动态流消失但行仍在
        async with self.Session() as db:
            nid = int((await db.execute(text("""
                SELECT note_id FROM community.notifications
                WHERE user_id=:f AND event_type='new_note' LIMIT 1
            """), {"f": self.follower})).scalar_one())
            await db.execute(text(
                "UPDATE community.notes SET visibility='private' WHERE id=:nid"
            ), {"nid": nid})
            await db.commit()

        feed = await self._feed()
        self.assertEqual(len(feed["items"]), 1)  # 隐藏行不进列表
        self.assertEqual(await self._unread(), 1)  # 未读数与列表同口径

        # 全量已读按收件人全量置位（含隐藏行, 不再挂未读）
        async with self.Session() as db:
            await notifications_svc.mark_all_read(db, self.follower)
            await db.commit()
        self.assertEqual(await self._unread(), 0)

    async def test_follow_event_lands_in_recipient_inbox(self):
        """写入侧经 owner 单发: 有人关注了你 → 收件人收件箱直达（不经扇出）。"""
        from api.services.notifications import notify_new_follower
        async with self.Session() as db:
            await notify_new_follower(db, self.follower, self.author)
            await db.commit()
        feed = await self._feed()
        self.assertEqual(feed["items"][0]["event_type"], "new_follower")
        self.assertIsNone(feed["items"][0]["read_at"])
        self.assertEqual(await self._unread(), 1)

    async def test_follow_user_endpoint_notifies_followed_user_once(self):
        from api.social import follow_user, unfollow_user
        username = f"nrs_a_{self.tag}"
        # 关注 → 取关 → 再关注 → 重复关注: 收件人只收一条 new_follower
        for action in (follow_user, unfollow_user, follow_user, follow_user):
            async with self.Session() as db:
                await action(username=username, actor=_actor(self.follower), db=db)
        feed = await self._feed(self.author)
        followers = [i for i in feed["items"] if i["event_type"] == "new_follower"]
        self.assertEqual(len(followers), 1)
        self.assertEqual(followers[0]["actor_username"], f"nrs_f_{self.tag}")
        self.assertEqual(await self._unread(self.author), 1)

    async def test_follow_reaction_endpoint_notifies_author_only_when_present(self):
        from api.social import follow_reaction
        authored = await self._insert_reaction(self.author)
        imported = await self._insert_reaction(None)
        for rid in (authored, imported, authored):
            async with self.Session() as db:
                await follow_reaction(reaction_id=rid, actor=_actor(self.follower), db=db)
        feed = await self._feed(self.author)
        favorited = [i for i in feed["items"] if i["event_type"] == "reaction_favorited"]
        self.assertEqual([i["reaction_id"] for i in favorited], [authored])
        async with self.engine.connect() as conn:
            orphan = (await conn.execute(text("""
                SELECT count(*) FROM community.notifications WHERE reaction_id=:r
            """), {"r": imported})).scalar_one()
        self.assertEqual(orphan, 0)


if __name__ == "__main__":
    unittest.main()
