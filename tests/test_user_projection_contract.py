"""用户投影四字段契约(username/display_name/avatar_url/active)。

凡是接口投影用户,同一组四字段一起出现 —— 头像与停用标记由数据驱动,
页面不再退化为只能显示首字母。直调服务/endpoint 函数 + 真链测试库
(与 test_users_search / test_notes_persistence_db 同法)。
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
    assert parse_qs(_u.query).get("test_sentinel") in (
        ["hgs-test-db"], ["hgs-ephemeral-db"])
    ASYNC_URL = re.sub(
        r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

USER_FIELDS = {"username", "display_name", "avatar_url", "active"}
FEED_ACTOR_FIELDS = {
    "actor_username", "actor_display_name", "actor_avatar_url", "actor_active"}


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class UserProjectionContractTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        self.user_ids: list[int] = []
        self.chemical_ids: list[int] = []
        async with self.engine.begin() as conn:
            self.owner = await self._insert_user(
                conn, "author", avatar="/avatars/author.png")
            self.reader = await self._insert_user(conn, "reader")
            self.gone = await self._insert_user(
                conn, "gone", status="disabled")
            self.chemical = int((await conn.execute(text("""
                INSERT INTO chemistry.chemicals(pubchem_cid,preferred_name,created_at,updated_at)
                VALUES (:cid,:name,now(),now()) RETURNING id
            """), {"cid": 1_800_000_000 + int(self.tag[:6], 16) % 90_000_000,
                   "name": f"proj-{self.tag}"})).scalar_one())
            self.chemical_ids.append(self.chemical)
            # 公开笔记挂在化合物上,作者带头像
            self.note = int((await conn.execute(text("""
                INSERT INTO community.notes(
                    owner_user_id,visibility,moderation_status,content)
                VALUES (:owner,'public','visible',:content) RETURNING id
            """), {"owner": self.owner,
                   "content": f"note body {self.tag}"})).scalar_one())
            await conn.execute(text("""
                INSERT INTO community.note_chemicals(note_id,chemical_id)
                VALUES (:note,:chem)
            """), {"note": self.note, "chem": self.chemical})
            # 动态: reader 关注作者, 作者发布公开笔记产生通知
            await conn.execute(text("""
                INSERT INTO community.user_follows(follower_user_id,followed_user_id)
                VALUES (:follower,:followed)
            """), {"follower": self.reader, "followed": self.owner})
            await conn.execute(text("""
                INSERT INTO community.notifications(
                    user_id,actor_user_id,event_type,note_id,dedupe_key)
                VALUES (:user,:actor,'new_note',:note,:dk)
                ON CONFLICT (dedupe_key) DO NOTHING
            """), {"user": self.reader, "actor": self.owner, "note": self.note,
                     "dk": f"proj-{self.tag}-{self.note}"})

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(text("""
                DELETE FROM community.notifications WHERE actor_user_id=ANY(:ids)
                   OR user_id=ANY(:ids)
            """), {"ids": self.user_ids})
            await conn.execute(text("""
                DELETE FROM community.user_follows WHERE follower_user_id=ANY(:ids)
                   OR followed_user_id=ANY(:ids)
            """), {"ids": self.user_ids})
            await conn.execute(text("""
                DELETE FROM community.note_chemicals WHERE chemical_id=ANY(:ids)
            """), {"ids": self.chemical_ids})
            await conn.execute(text("""
                DELETE FROM community.notes WHERE id=:note
            """), {"note": self.note})
            await conn.execute(text("""
                DELETE FROM community.users WHERE id=ANY(:ids)
            """), {"ids": self.user_ids})
            await conn.execute(text("""
                DELETE FROM chemistry.chemicals WHERE id=ANY(:ids)
            """), {"ids": self.chemical_ids})
        await self.engine.dispose()

    async def _insert_user(self, conn, suffix: str, *,
                           avatar: str | None = None,
                           status: str = "active") -> int:
        row = (await conn.execute(text("""
            INSERT INTO community.users(
                username,email,password_hash,display_name,avatar_path,status)
            VALUES (:u,:e,'x',:d,:avatar,:status) RETURNING id
        """), {
            "u": f"proj_{suffix}_{self.tag}",
            "e": f"proj_{suffix}_{self.tag}@example.test",
            "d": f"Projection {suffix}",
            "avatar": avatar,
            "status": status,
        })).scalar_one()
        self.user_ids.append(int(row))
        return int(row)

    # ── 笔记族 ──────────────────────────────────────────────

    async def test_note_detail_carries_owner_avatar_and_active(self):
        from api.services.notes import get_note
        async with self.Session() as db:
            note = await get_note(db, note_id=self.note, actor_id=None)
        self.assertTrue(USER_FIELDS <= set(note))
        self.assertEqual(note["avatar_url"], "/avatars/author.png")
        self.assertIs(note["active"], True)
        self.assertNotIn("owner_active", note)

    async def test_entity_note_list_carries_owner_avatar_and_active(self):
        from api.services.notes import list_entity_notes
        async with self.Session() as db:
            page = await list_entity_notes(
                db, entity="chemical", entity_id=self.chemical, page=1, page_size=10)
        self.assertEqual(len(page["items"]), 1)
        for item in page["items"]:
            self.assertTrue(USER_FIELDS <= set(item))
            self.assertEqual(item["avatar_url"], "/avatars/author.png")
            self.assertIs(item["active"], True)

    async def test_public_user_notes_carries_avatar_and_active(self):
        from api.services.notes import list_public_user_notes
        async with self.Session() as db:
            page = await list_public_user_notes(
                db, user_id=self.owner, page=1, page_size=10)
        for item in page["items"]:
            self.assertTrue(USER_FIELDS <= set(item))

    async def test_my_notes_carries_avatar_and_active(self):
        from api.services.notes import list_my_notes
        async with self.Session() as db:
            page = await list_my_notes(
                db, actor_id=self.owner, visibility="all", page=1, page_size=10,
                chemical_id=None, reaction_id=None)
        for item in page["items"]:
            self.assertTrue(USER_FIELDS <= set(item))

    # ── 动态 ────────────────────────────────────────────────

    async def test_activity_feed_carries_actor_avatar_and_active(self):
        import api.social as social
        from api.core.security import Actor
        actor = Actor(self.reader, "u", "U", "u@example.test", "member",
                      None, "session")
        async with self.Session() as db:
            feed = await social.notifications(
                page=1, page_size=10, actor=actor, db=db)
        self.assertTrue(feed["items"])
        for item in feed["items"]:
            self.assertTrue(FEED_ACTOR_FIELDS <= set(item))
            self.assertEqual(item["actor_avatar_url"], "/avatars/author.png")
            self.assertIs(item["actor_active"], True)

    # ── 用户档案族 ──────────────────────────────────────────

    async def test_public_profile_active_field_name(self):
        import api.users as users_api
        from api.core.security import Actor
        viewer = Actor(self.reader, "u", "U", "u@example.test", "member",
                       None, "session")
        async with self.Session() as db:
            profile = await users_api.public_profile(
                username=f"proj_author_{self.tag}", actor=viewer, db=db)
            gone = await users_api.public_profile(
                username=f"proj_gone_{self.tag}", actor=None, db=db)
        self.assertIs(profile["active"], True)
        self.assertNotIn("is_active", profile)
        self.assertEqual(profile["avatar_url"], "/avatars/author.png")
        # 停用档案: active=False 的最小信息卡
        self.assertIs(gone["active"], False)
        self.assertNotIn("is_active", gone)

    async def test_user_search_carries_active(self):
        import api.users as users_api

        class _NoIpRequest:
            headers: dict[str, str] = {}

        async with self.Session() as db:
            result = await users_api.search_users(
                request=_NoIpRequest(), q=f"proj_author_{self.tag}",
                page=1, page_size=10, actor=None, db=db)
        self.assertTrue(result["users"])
        for u in result["users"]:
            self.assertTrue(USER_FIELDS <= set(u))
            self.assertIs(u["active"], True)

    async def test_followers_list_carries_active(self):
        from api.users import relationship_page
        async with self.Session() as db:
            page = await relationship_page(
                f"proj_author_{self.tag}", "followers", 1, 10, None, db)
        for item in page["items"]:
            self.assertTrue(USER_FIELDS <= set(item))

    async def test_dashboard_carries_active(self):
        import api.users as users_api
        from api.core.security import Actor
        actor = Actor(self.owner, "u", "U", "u@example.test", "member",
                      None, "session")
        async with self.Session() as db:
            summary = await users_api.dashboard_summary(actor=actor, db=db)
        self.assertIs(summary["active"], True)
        self.assertEqual(summary["avatar_url"], "/avatars/author.png")

    # ── 会话自述 ────────────────────────────────────────────

    def test_actor_payload_carries_active(self):
        from api.core.security import Actor, actor_payload
        actor = Actor(1, "u", "U", "u@example.test", "member",
                      "/avatars/x.png", "session")
        payload = actor_payload(actor)
        self.assertIs(payload["active"], True)
        self.assertEqual(payload["avatar_url"], "/avatars/x.png")


if __name__ == "__main__":
    unittest.main()
