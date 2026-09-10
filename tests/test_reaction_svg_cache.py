"""Reaction SVG cacheability (LOW-PATCH, 2026-09-10)。

shared-cache eligibility = visibility public AND moderation visible —
不基于 actor 身份(public+visible 即使 owner/admin 请求, 匿名同样有权;
public+hidden 即使 owner/admin 有权读取, 也不可 shared-cache)。
TTL 5min; 接受最终一致性(转私/隐藏/删除后旧 SVG 最多存活约 5 分钟)。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip  # noqa: E402
    DB_URL = test_db_or_skip()
except Exception:  # noqa: BLE001
    DB_URL = None

if DB_URL:
    if not DB_URL.startswith("postgresql+asyncpg://"):
        DB_URL = "postgresql+asyncpg://" + DB_URL.split("://", 1)[1]
    DB_URL = DB_URL.split("?", 1)[0]

OWNER_ID = 3   # member, owns reactions 930011-930013
ADMIN_ID = 4   # admin
R_PUBLIC_VISIBLE = 930011
R_PUBLIC_HIDDEN = 930012
R_PRIVATE = 930013


def _actor(user_id: int | None, role: str | None):
    if user_id is None:
        return None
    from api.core.security import Actor
    return Actor(id=user_id, username=f"ut5svg{user_id}",
                 display_name=f"UT{user_id}", email=f"ut{user_id}@t.example",
                 role=role, avatar_path=None, auth_kind="web")


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDB:
    """绕开真实 DB 也绕不开: 直接用真库查到的固定行形态(见真链测试)。"""

    def __init__(self, row):
        self._row = row

    async def execute(self, *_a, **_k):
        return _FakeResult(self._row)


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
class ReactionSvgCacheTests(unittest.TestCase):
    """真链: 真 render_reaction + 真 DB fixture 行(不 mock SQL 授权)。"""

    @classmethod
    def setUpClass(cls):
        import random as _random
        from sqlalchemy import text
        os.environ.setdefault(
            "HGS_DATABASE_URL",
            os.environ.get("TEST_DATABASE_URL",
                           "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs"))
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        cls.engine = create_async_engine(DB_URL, poolclass=NullPool)
        # 自建 fixture(fresh baseline 库无历史行): owner member + 三条 reaction
        # public visible / public hidden / private
        run = _random.randint(10_000_000, 99_000_000)

        async def _seed():
            async with cls.engine.begin() as db:
                rows = (await db.execute(text("""
                    INSERT INTO community.users
                      (username,email,password_hash,role,display_name)
                    VALUES (:u,:e1,'x','member','U'),
                           (:a,:e2,'x','admin','A')
                    RETURNING id, role
                """), {"u": f"utsvg{run}", "a": f"utsvga{run}",
                     "e1": f"svg{run}@t.example", "e2": f"svga{run}@t.example"})).fetchall()
                uid = next(r[0] for r in rows if r[1] == "member")
                admin_uid = next(r[0] for r in rows if r[1] == "admin")
                rids = (await db.execute(text("""
                    INSERT INTO chemistry.reactions
                      (reaction_smiles,created_by_user_id,visibility,
                       moderation_status,source_type)
                    VALUES
                      ('C>>O', :uid, 'public',  'visible', 'self'),
                      ('C>>N', :uid, 'public',  'hidden',  'self'),
                      ('C>>S', :uid, 'private', 'visible', 'self')
                    RETURNING id
                """), {"uid": uid})).fetchall()
                return uid, admin_uid, [r[0] for r in rids]

        cls._own_id, _admin_id, _rids = asyncio.run(_seed())
        # discover 会以 tests.xxx 与裸 xxx 双名装载本模块(两份全局命名空间),
        # 类属性+两类模块全局三处同绑, 保证 test 方法看到 seed id。
        import sys
        cls.OWNER_ID = cls._own_id
        cls.ADMIN_ID = _admin_id
        cls.R_PUBLIC_VISIBLE = _rids[0]
        cls.R_PUBLIC_HIDDEN = _rids[1]
        cls.R_PRIVATE = _rids[2]
        for _name in ("tests.test_reaction_svg_cache",
                      "test_reaction_svg_cache"):
            _mod = sys.modules.get(_name)
            if _mod is not None:
                _mod.OWNER_ID = cls._own_id
                _mod.ADMIN_ID = _admin_id
                _mod.R_PUBLIC_VISIBLE = _rids[0]
                _mod.R_PUBLIC_HIDDEN = _rids[1]
                _mod.R_PRIVATE = _rids[2]

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cls.engine.dispose())

    def _render(self, reaction_id: int, actor):
        from api.mol import render_reaction

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as session:
                return await render_reaction(
                    reaction_id=reaction_id, w=1200, h=300,
                    actor=actor, db=session)

        try:
            return asyncio.run(go())
        except Exception as exc:  # noqa: BLE001
            return exc

    def _status(self, resp) -> int:
        from fastapi import HTTPException
        if isinstance(resp, HTTPException):
            return resp.status_code
        return resp.status_code

    def _cc(self, resp) -> str:
        return resp.headers["cache-control"]

    # 1. anonymous + public + visible → public, max-age=300
    def test_1_anon_public_visible_shareable(self):
        resp = self._render(R_PUBLIC_VISIBLE, None)
        self.assertEqual(self._status(resp), 200)
        self.assertEqual(self._cc(resp), "public, max-age=300")

    # 2. owner + public + hidden → private, no-store
    def test_2_owner_public_hidden_private(self):
        resp = self._render(R_PUBLIC_HIDDEN, _actor(OWNER_ID, "member"))
        self.assertEqual(self._status(resp), 200)
        self.assertEqual(self._cc(resp), "private, no-store")

    # 3. admin + public + hidden → private, no-store
    def test_3_admin_public_hidden_private(self):
        resp = self._render(R_PUBLIC_HIDDEN, _actor(ADMIN_ID, "admin"))
        self.assertEqual(self._status(resp), 200)
        self.assertEqual(self._cc(resp), "private, no-store")

    # 4. owner + private → private, no-store
    def test_4_owner_private_no_store(self):
        resp = self._render(R_PRIVATE, _actor(OWNER_ID, "member"))
        self.assertEqual(self._status(resp), 200)
        self.assertEqual(self._cc(resp), "private, no-store")

    # 5. anonymous + private / public-hidden → 404
    def test_5_anon_private_and_hidden_404(self):
        self.assertEqual(
            self._status(self._render(R_PRIVATE, None)), 404)
        self.assertEqual(
            self._status(self._render(R_PUBLIC_HIDDEN, None)), 404)

    # 6. owner + public + visible → 仍可 shared-cache(匿名同权)
    def test_7_owner_public_visible_shareable(self):
        resp = self._render(R_PUBLIC_VISIBLE, _actor(OWNER_ID, "member"))
        self.assertEqual(self._status(resp), 200)
        self.assertEqual(self._cc(resp), "public, max-age=300")

    # 静态断言: reaction SVG 响应不再出现 immutable
    def test_6_no_immutable_in_reaction_svg_path(self):
        import api.mol as mol
        src = inspect.getsource(mol.render_reaction)
        self.assertNotIn("immutable", src)
        # shared-cache 判定必须同时看 visibility 和 moderation_status
        self.assertIn('row[2] == "public" and row[3] == "visible"', src)
        # molecule svg/png 端点(108/139 行)不在本函数内 — 不受影响


if __name__ == "__main__":
    unittest.main()
