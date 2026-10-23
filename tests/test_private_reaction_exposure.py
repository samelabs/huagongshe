"""私有反应暴露面矩阵 —— 匿名/其他登录用户/本人 三身份逐出口核对。

每个出口(详情/检索/用户列表/化合物相关反应/动态/站点地图/公开笔记徽标/
渲染图缓存)在三种身份下的预期唯一化: 匿名与他人只见公开+可见,
本人(与管理员)可见自己的私有; 带身份的渲染响应恒 private,no-store。
直调服务与 endpoint 函数 + 真链测试库。
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

RX_SMILES = "c1ccccc1O>>c1ccccc1Cl"


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class PrivateReactionExposureTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        self.user_ids: list[int] = []
        self.reaction_ids: list[int] = []
        self.chemical_ids: list[int] = []
        async with self.engine.begin() as conn:
            self.owner = await self._insert_user(conn, "owner")
            self.other = await self._insert_user(conn, "other")
            self.chemical = int((await conn.execute(text("""
                INSERT INTO chemistry.chemicals(pubchem_cid,preferred_name,created_at,updated_at)
                VALUES (:cid,:name,now(),now()) RETURNING id
            """), {"cid": 1_900_000_000 + int(self.tag[:6], 16) % 90_000_000,
                   "name": f"expo-{self.tag}"})).scalar_one())
            self.chemical_ids.append(self.chemical)
            self.public_rx = await self._insert_reaction(conn, "public")
            self.private_rx = await self._insert_reaction(conn, "private")
            for rx in (self.public_rx, self.private_rx):
                await conn.execute(text("""
                    INSERT INTO chemistry.reaction_chemicals(
                        reaction_id,chemical_id,role,occurrence_count)
                    VALUES (:rx,:chem,'REACTANT',1)
                """), {"rx": rx, "chem": self.chemical})
            # 本人公开笔记挂自己的私有反应(公开笔记挂私有反应的唯一合法路径:
            # 挂时公开, 之后反应转私有)
            _n = (await conn.execute(text("""
                INSERT INTO community.notes(
                    owner_user_id,visibility,moderation_status,content,slug)
                VALUES (:owner,'public','visible',:content,:slug) RETURNING id, slug
            """), {"owner": self.owner, "slug": self.tag[:7],
                   "content": f"expo note {self.tag}"}
            )).first()
            self.note, self.note_slug = int(_n[0]), str(_n[1])
            await conn.execute(text("""
                INSERT INTO community.note_reactions(note_id,reaction_id)
                VALUES (:note,:rx)
            """), {"note": self.note, "rx": self.private_rx})
            # 他人关注作者 → 动态受众
            await conn.execute(text("""
                INSERT INTO community.user_follows(follower_user_id,followed_user_id)
                VALUES (:follower,:followed)
            """), {"follower": self.other, "followed": self.owner})
            await conn.execute(text("""
                INSERT INTO community.notifications(
                    user_id,actor_user_id,event_type,reaction_id,dedupe_key)
                VALUES (:user,:actor,'new_reaction',:rx,:dk)
                ON CONFLICT (dedupe_key) DO NOTHING
            """), {"user": self.other, "actor": self.owner,
                   "rx": self.private_rx, "dk": f"expo-{self.tag}-private"})
            await conn.execute(text("""
                INSERT INTO community.notifications(
                    user_id,actor_user_id,event_type,reaction_id,dedupe_key)
                VALUES (:user,:actor,'new_reaction',:rx,:dk)
                ON CONFLICT (dedupe_key) DO NOTHING
            """), {"user": self.other, "actor": self.owner,
                   "rx": self.public_rx, "dk": f"expo-{self.tag}-public"})

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
                DELETE FROM community.note_reactions WHERE note_id=:note
            """), {"note": self.note})
            await conn.execute(text("""
                DELETE FROM community.notes WHERE id=:note
            """), {"note": self.note})
            await conn.execute(text("""
                DELETE FROM chemistry.reaction_chemicals WHERE chemical_id=ANY(:ids)
            """), {"ids": self.chemical_ids})
            await conn.execute(text("""
                DELETE FROM chemistry.reactions WHERE id=ANY(:ids)
            """), {"ids": self.reaction_ids})
            await conn.execute(text("""
                DELETE FROM community.users WHERE id=ANY(:ids)
            """), {"ids": self.user_ids})
            await conn.execute(text("""
                DELETE FROM chemistry.chemicals WHERE id=ANY(:ids)
            """), {"ids": self.chemical_ids})
        await self.engine.dispose()

    async def _insert_user(self, conn, suffix: str) -> int:
        row = int((await conn.execute(text("""
            INSERT INTO community.users(username,email,password_hash,display_name)
            VALUES (:u,:e,'x',:d) RETURNING id
        """), {
            "u": f"expo_{suffix}_{self.tag}",
            "e": f"expo_{suffix}_{self.tag}@example.test",
            "d": f"Exposure {suffix}",
        })).scalar_one())
        self.user_ids.append(row)
        return row

    async def _insert_reaction(self, conn, visibility: str) -> int:
        row = int((await conn.execute(text("""
            INSERT INTO chemistry.reactions(
                created_by_user_id,visibility,moderation_status,created_via,
                source_type,reaction_smiles)
            VALUES (:owner,:visibility,'visible','web','self',:smiles)
            RETURNING id
        """), {"owner": self.owner, "visibility": visibility,
                "smiles": RX_SMILES})).scalar_one())
        self.reaction_ids.append(row)
        return row

    # ── 反应详情 ───────────────────────────────────────────

    async def test_reaction_detail_identity_matrix(self):
        from api.services.reactions import load_reaction_detail
        async with self.Session() as db:
            anon = await load_reaction_detail(db, self.private_rx, 0, False)
            other = await load_reaction_detail(db, self.private_rx, self.other, False)
            owner = await load_reaction_detail(db, self.private_rx, self.owner, False)
            admin = await load_reaction_detail(db, self.private_rx, self.other, True)
            anon_pub = await load_reaction_detail(db, self.public_rx, 0, False)
        self.assertIsNone(anon, "匿名不得读到私有反应")
        self.assertIsNone(other, "其他登录用户不得读到私有反应")
        self.assertIsNotNone(owner, "本人可读自己的私有反应")
        self.assertIsNotNone(admin, "管理员可读私有反应")
        self.assertIsNotNone(anon_pub)

    # ── 统一检索 ───────────────────────────────────────────

    async def test_search_lookup_keeps_private_reaction_outside_owner(self):
        from api.services.chemicals import reaction_lookup
        async with self.Session() as db:
            anon = await reaction_lookup(db, str(self.private_rx), 10, actor_id=None)
            other = await reaction_lookup(db, str(self.private_rx), 10, actor_id=self.other)
            owner = await reaction_lookup(db, str(self.private_rx), 10, actor_id=self.owner)
        ids = lambda rows: {r["id"] for r in rows}
        self.assertNotIn(self.private_rx, ids(anon))
        self.assertNotIn(self.private_rx, ids(other))
        self.assertIn(self.private_rx, ids(owner))

    # ── 用户主页反应列表 ────────────────────────────────────

    async def test_user_reactions_lists_public_only(self):
        import api.reactions as reactions_api
        from api.core.security import Actor
        for actor in (None, Actor(self.other, "u", "U", "u@t.example", "member",
                                  None, "session")):
            async with self.Session() as db:
                rows = await reactions_api.user_reactions(
                    username=f"expo_owner_{self.tag}", page=1, page_size=50,
                    actor=actor, db=db)
            listed = {r["id"] for r in rows}
            self.assertIn(self.public_rx, listed)
            self.assertNotIn(self.private_rx, listed,
                             "用户主页反应列表不得出现私有(即使本人观看)")

    async def test_user_reactions_participants_projected_by_name(self):
        import api.reactions as reactions_api
        async with self.Session() as db:
            rows = await reactions_api.user_reactions(
                username=f"expo_owner_{self.tag}", page=1, page_size=50,
                actor=None, db=db)
        target = next(r for r in rows if r["id"] == self.public_rx)
        (participant,) = target["participants"]
        # 参与物按列名投影：角色/收率来自 rc 列，化学品字段来自化学品列，
        # 投影列的顺序或数量变化必须显式报错而不是静默错位
        self.assertEqual(participant["role"], "REACTANT")
        self.assertIsNone(participant["yield_percent"])
        self.assertEqual(participant["id"], self.chemical)
        self.assertEqual(participant["preferred_name"], f"expo-{self.tag}")

    # ── 化合物详情页相关反应 ─────────────────────────────────

    async def test_chemical_related_reactions_exclude_private(self):
        from api.services.chemicals import reaction_summaries
        async with self.Session() as db:
            total, items = await reaction_summaries(
                db, [self.chemical], "any", 1, 50)
        ids = {i["id"] for i in items}
        self.assertIn(self.public_rx, ids)
        self.assertNotIn(self.private_rx, ids)
        self.assertEqual(total, 1)

    # ── 动态 ────────────────────────────────────────────────

    async def test_activity_feed_hides_private_reaction_event(self):
        import api.social as social
        from api.core.security import Actor
        actor = Actor(self.other, "u", "U", "u@t.example", "member", None, "session")
        async with self.Session() as db:
            feed = await social.notifications(page=1, page_size=50, actor=actor, db=db)
        rx_ids = {i["reaction_id"] for i in feed["items"]}
        self.assertIn(self.public_rx, rx_ids)
        self.assertNotIn(self.private_rx, rx_ids, "动态不得出现私有反应事件")

    # ── 站点地图 ────────────────────────────────────────────

    async def test_sitemap_reactions_public_only(self):
        from api.services.chemicals import load_sitemap_reactions
        async with self.Session() as db:
            page = await load_sitemap_reactions(db, 0, 50000)
        ids = {r["id"] for r in page["reactions"]}
        self.assertIn(self.public_rx, ids)
        self.assertNotIn(self.private_rx, ids)

    # ── 公开笔记的反应徽标 ──────────────────────────────────

    async def test_public_note_hides_private_reaction_badge(self):
        from api.services.notes import get_note
        async with self.Session() as db:
            anon_note = await get_note(db, note_ref=self.note_slug, actor_id=None)
            other_note = await get_note(db, note_ref=self.note_slug, actor_id=self.other)
            owner_note = await get_note(db, note_ref=self.note_slug, actor_id=self.owner)
        self.assertNotIn(self.private_rx, anon_note["reaction_ids"],
                         "匿名读公开笔记不得看到私有反应 HRID")
        self.assertNotIn(self.private_rx, other_note["reaction_ids"])
        self.assertIn(self.private_rx, owner_note["reaction_ids"],
                      "本人的公开笔记里自己可见私有反应引用")

    # ── 渲染图(/img 的上游) ─────────────────────────────────

    async def test_reaction_render_cache_matrix(self):
        from api.core.security import Actor
        from api.mol import render_reaction
        from fastapi import HTTPException

        anon_actor = None
        other_actor = Actor(self.other, "u", "U", "u@t.example", "member",
                            None, "session")
        owner_actor = Actor(self.owner, "u", "U", "u@t.example", "member",
                            None, "session")
        async with self.Session() as db:
            with self.assertRaises(HTTPException) as cm:
                await render_reaction(self.private_rx, actor=anon_actor, db=db)
            self.assertEqual(cm.exception.status_code, 404)
            with self.assertRaises(HTTPException) as cm:
                await render_reaction(self.private_rx, actor=other_actor, db=db)
            self.assertEqual(cm.exception.status_code, 404)
            owner_res = await render_reaction(self.private_rx, actor=owner_actor, db=db)
            self.assertEqual(owner_res.headers["cache-control"], "private, no-store")
            anon_res = await render_reaction(self.public_rx, actor=anon_actor, db=db)
        self.assertEqual(anon_res.headers["cache-control"], "public, max-age=300")


if __name__ == "__main__":
    unittest.main()
