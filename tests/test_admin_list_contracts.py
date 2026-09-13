"""Admin list contract tests: users + reactions (hermetic fixtures).

契约 (Batch 1 起, 不保留旧裸数组 shape):
  GET /admin/users?q=&limit=&offset=          -> {"total": N, "items": [...]}
  GET /admin/reactions?status=&limit=&offset= -> {"total": N, "items": [...]}

Hermetic 原则 (本轮收口):
  - 两套测试均自造唯一 RUN marker 数据, 不依赖测试库任何存量;
    GitHub fresh test_hgs 与服务器共享 test_hgs (含历史数据) 都必须通过。
  - reactions 期望值 = 真实 DB 过滤 count + marker 差值, 不写死环境快照数字。

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_admin_list_contracts
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

try:
    from tests.db_gate import test_db_or_skip  # noqa: E402

    _RAW = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + _RAW.split("://", 1)[1].split("?", 1)[0]
except Exception:  # pragma: no cover - 无 test DB 时跳过 DB 用例
    DB_URL = None

RUN = os.urandom(3).hex()


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DB_URL)


async def _seed_users(n: int) -> list[int]:
    """造 n 个 marker 用户 (旧 id 区间在前), 返回 ids。清理由 _cleanup 负责。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    eng = _engine()
    ids: list[int] = []
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as db:
            for i in range(n):
                uid = (await db.execute(text("""
                    INSERT INTO community.users (username,email,password_hash,role,display_name)
                    VALUES (:u,:e,'x','member','U') RETURNING id
                """), {"u": f"lc{RUN}{i:03d}", "e": f"lc{RUN}{i:03d}@t.example"})).scalar()
                ids.append(int(uid))
            await db.commit()
    finally:
        await eng.dispose()
    return ids


async def _cleanup_users(ids: list[int]) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    eng = _engine()
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as db:
            for uid in ids:
                await db.execute(text("DELETE FROM community.users WHERE id=:i"), {"i": uid})
            await db.commit()
    finally:
        await eng.dispose()


# ---- reactions hermetic fixture -------------------------------------------
# marker owner 1 个 + 7 条 user reactions (5 visible / 2 hidden) + 1 条 system
# reaction (created_by_user_id NULL)。全部带 reaction_smiles = RUN marker,
# 清理按 marker 前缀删除, 不碰库内任何其它行。

_SMILES = f"{RUN}>>C(=O)O"  # 非法化学也无妨: 列是裸 text, 契约不解析


async def _seed_reactions() -> tuple[int, list[int]]:
    """返回 (owner_user_id, reaction_ids)。7 user (5 visible/2 hidden) + 1 system。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    eng = _engine()
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as db:
            owner = (await db.execute(text("""
                INSERT INTO community.users (username,email,password_hash,role,display_name)
                VALUES (:u,:e,'x','member','R') RETURNING id
            """), {"u": f"rc{RUN}own", "e": f"rc{RUN}@t.example"})).scalar()
            rids: list[int] = []
            for i, status in enumerate(
                ["visible", "visible", "visible", "visible", "visible", "hidden", "hidden"]
            ):
                rid = (await db.execute(text("""
                    INSERT INTO chemistry.reactions
                        (reaction_smiles, created_by_user_id, source_type,
                         visibility, moderation_status)
                    VALUES (:s, :u, 'self', 'public', :m) RETURNING id
                """), {"s": _SMILES, "u": owner, "m": status})).scalar()
                rids.append(int(rid))
            # system row: created_by_user_id NULL → 任何 status 的 total/items 都不得含它
            sys_rid = (await db.execute(text("""
                INSERT INTO chemistry.reactions (reaction_smiles, created_by_user_id)
                VALUES (:s, NULL) RETURNING id
            """), {"s": _SMILES})).scalar()
            rids.append(int(sys_rid))
            await db.commit()
            return int(owner), rids
    finally:
        await eng.dispose()


async def _cleanup_reactions(owner: int, rids: list[int]) -> None:
    """按 id 精确删除 marker reactions + owner; 再按 smiles marker 兜底清残。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    eng = _engine()
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as db:
            await db.execute(text(
                "DELETE FROM chemistry.reactions WHERE id = ANY(:ids) OR reaction_smiles = :s"
            ), {"ids": rids, "s": _SMILES})
            await db.execute(text("DELETE FROM community.users WHERE id=:i"), {"i": owner})
            await db.commit()
    finally:
        await eng.dispose()


async def _db_count(where: str) -> int:
    """真实 DB count (真实过滤条件, 不含 marker 差值)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    eng = _engine()
    try:
        async with async_sessionmaker(eng)() as db:
            return int((await db.execute(text(
                f"SELECT count(*) FROM chemistry.reactions {where}"
            ))).scalar_one())
    finally:
        await eng.dispose()


async def _call_admin(path: str, actor_id: int):
    """最小 ASGI app: 只挂 admin router, dependency_overrides 注入 admin actor + 测试库 session。"""
    import httpx
    from fastapi import FastAPI

    from api.admin import router as admin_router
    from api.core.database import get_db
    from api.core.security import Actor
    from api import admin as admin_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    app = FastAPI()
    app.include_router(admin_router, prefix="/api")

    eng = create_async_engine(DB_URL)
    session_factory = async_sessionmaker(eng, expire_on_commit=False)

    async def _test_db():
        async with session_factory() as s:
            yield s

    def _admin_actor() -> Actor:
        return Actor(id=actor_id, username="lcadmin", display_name="lc",
                     email="lc@t.example", role="admin", avatar_path=None,
                     auth_kind="session")

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[admin_module.admin] = _admin_actor
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get(f"/api{path}")
            return r.status_code, (r.json() if r.status_code == 200 else None)
    finally:
        await eng.dispose()


# admin actor 需要真实存在于 users 表 (per-user 子查询不受影响, 但 self-check 不查表;
# dependency_overrides 直接注入 actor, 无需 DB 行 —— actor_id 用 0 即可)


@unittest.skipUnless(DB_URL, "需要 test DB")
class UsersListContractTests(unittest.IsolatedAsyncioTestCase):
    """U1-U4: users 分页/total/search nuance/参数边界 (hermetic marker)。"""

    SEED = 7   # seed 7 个 marker 用户, 用 limit=3 窗口化
    ids: list[int] = []

    @classmethod
    def setUpClass(cls):
        cls.ids = asyncio_run(_seed_users(cls.SEED))

    @classmethod
    def tearDownClass(cls):
        asyncio_run(_cleanup_users(cls.ids))

    async def test_u1_pagination_windows_desc_no_overlap(self):
        """U1: total > len(items); 两窗口不重叠; ORDER BY id DESC。"""
        code, body = await _call_admin(f"/admin/users?limit=3&offset=0", 0)
        self.assertEqual(200, code)
        self.assertIn("total", body); self.assertIn("items", body)
        all_ids = self.ids
        # marker 用户是最新插入的 → 全部应出现在前两窗 (7 个, 窗口 3+3)
        w1, w2 = body["items"], None
        self.assertEqual(3, len(w1))
        self.assertGreater(body["total"], len(w1))
        code, w2body = await _call_admin(f"/admin/users?limit=3&offset=3", 0)
        self.assertEqual(200, code)
        w2 = w2body["items"]
        self.assertEqual(3, len(w2))
        ids1 = {u["id"] for u in w1}
        ids2 = {u["id"] for u in w2}
        self.assertFalse(ids1 & ids2, "offset 窗口不得重叠")
        # id DESC: w1 最小 id 也要 > w2 最大 id (marker 区间内)
        marker1 = sorted(i for i in ids1 if i in all_ids)
        marker2 = sorted(i for i in ids2 if i in all_ids)
        if marker1 and marker2:
            self.assertLess(marker2[-1], marker1[0] if not (ids1 - set(all_ids)) else marker1[0])
        # 第一窗口 = 全体 DESC 的前 3
        desc_all = sorted(all_ids, reverse=True)[:3]
        self.assertEqual(desc_all, [u["id"] for u in w1])

    async def test_u2_q_total_same_filter(self):
        """U2: q 过滤后 total 与 items 来自同一集合。"""
        u = f"lc{RUN}000"
        code, body = await _call_admin(f"/admin/users?q={u}&limit=100&offset=0", 0)
        self.assertEqual(200, code)
        self.assertEqual(1, body["total"])
        self.assertEqual(1, len(body["items"]))
        self.assertEqual(u, body["items"][0]["username"])

    async def test_u3_old_user_search_nuance(self):
        """U3: 最老 marker 不在默认第一页, 但 q=username 可达 (审计纠偏锁)。"""
        oldest = min(self.ids)
        code, first_page = await _call_admin("/admin/users?limit=3&offset=0", 0)
        self.assertNotIn(oldest, [u["id"] for u in first_page["items"]],
                         "最老 marker 不应出现在第一窗口 (DESC)")
        code, hit = await _call_admin(f"/admin/users?q=lc{RUN}000&limit=100", 0)
        self.assertEqual(200, code)
        self.assertIn(oldest, [u["id"] for u in hit["items"]],
                      "老用户 q 精确搜索后必须可达")

    async def test_u4_param_boundaries(self):
        """U4: offset<0 / limit>100 => 422。"""
        code, _ = await _call_admin("/admin/users?limit=101", 0)
        self.assertEqual(422, code)
        code, _ = await _call_admin("/admin/users?limit=3&offset=-1", 0)
        self.assertEqual(422, code)


@unittest.skipUnless(DB_URL, "需要 test DB")
class ReactionsListContractTests(unittest.IsolatedAsyncioTestCase):
    """R1-R4: reactions 窗口/total 口径/status filter/参数边界。

    Hermetic: 自造 marker (owner + 7 user-reactions 5 visible/2 hidden + 1 system row)。
    total 断言 = DB 真实 count + marker 差值 (不依赖库存量, fresh/共享库都成立)。
    """

    MARKER_USER_ROWS = 7      # 5 visible + 2 hidden
    MARKER_VISIBLE = 5
    MARKER_HIDDEN = 2

    owner: int = 0
    rids: list[int] = []

    @classmethod
    def setUpClass(cls):
        cls.owner, cls.rids = asyncio_run(_seed_reactions())

    @classmethod
    def tearDownClass(cls):
        asyncio_run(_cleanup_reactions(cls.owner, cls.rids))

    async def test_r1_offset_window_stable(self):
        """R1: API 窗口 = DB 同 WHERE/ORDER/LIMIT/OFFSET 直查结果 (fresh/共享库都成立)。"""
        from sqlalchemy import text as _t
        from sqlalchemy.ext.asyncio import async_sessionmaker

        eng = _engine()
        try:
            async with async_sessionmaker(eng)() as db:
                db_w1 = (await db.execute(_t(
                    "SELECT id FROM chemistry.reactions "
                    "WHERE created_by_user_id IS NOT NULL "
                    "ORDER BY id DESC LIMIT 3 OFFSET 0"))).scalars().all()
                db_w2 = (await db.execute(_t(
                    "SELECT id FROM chemistry.reactions "
                    "WHERE created_by_user_id IS NOT NULL "
                    "ORDER BY id DESC LIMIT 3 OFFSET 3"))).scalars().all()
        finally:
            await eng.dispose()

        code, w1 = await _call_admin("/admin/reactions?status=all&limit=3&offset=0", 0)
        self.assertEqual(200, code)
        self.assertEqual([int(x) for x in db_w1], [r["id"] for r in w1["items"]],
                         "API 第一窗口必须与 DB 直查完全一致")
        code, w2 = await _call_admin("/admin/reactions?status=all&limit=3&offset=3", 0)
        self.assertEqual(200, code)
        ids1 = [r["id"] for r in w1["items"]]
        ids2 = [r["id"] for r in w2["items"]]
        self.assertEqual([int(x) for x in db_w2], ids2)
        self.assertFalse(set(ids1) & set(ids2), "窗口不得重叠")
        self.assertEqual(ids1, sorted(ids1, reverse=True), "ORDER BY id DESC")

    async def test_r2_total_excludes_system_rows(self):
        """R2: status=all 的 total = DB 真实 user-reactions count (含 marker, 排除 system)。"""
        expect = await _db_count("WHERE created_by_user_id IS NOT NULL")
        code, body = await _call_admin("/admin/reactions?status=all&limit=1", 0)
        self.assertEqual(200, code)
        self.assertEqual(expect, body["total"])
        if expect > 1:
            self.assertLess(len(body["items"]), body["total"], "total > len(items) (limit=1)")
        # system marker row (created_by_user_id NULL) 不得出现在 items/total 口径内:
        # 直接对 marker sys id 做 q 不存在 → 用窗口全量验证: sys rid 不在任何 user-reaction 集合
        marker_total = await _db_count(
            f"WHERE created_by_user_id IS NOT NULL AND reaction_smiles = '{_SMILES}'")
        self.assertEqual(self.MARKER_USER_ROWS, marker_total,
                         "marker user-reactions 应全部计入 total 口径")

    async def test_r3_status_filter_total_same_set(self):
        """R3: visible/hidden total = DB 各自真实过滤集合; visible+hidden==all。"""
        exp_v = await _db_count(
            "WHERE created_by_user_id IS NOT NULL AND moderation_status='visible'")
        exp_h = await _db_count(
            "WHERE created_by_user_id IS NOT NULL AND moderation_status='hidden'")
        code, v = await _call_admin("/admin/reactions?status=visible&limit=1", 0)
        code2, h = await _call_admin("/admin/reactions?status=hidden&limit=1", 0)
        self.assertEqual(200, code); self.assertEqual(200, code2)
        self.assertEqual(exp_v, v["total"])
        self.assertEqual(exp_h, h["total"])
        code, a = await _call_admin("/admin/reactions?status=all&limit=1", 0)
        self.assertEqual(exp_v + exp_h, a["total"], "visible + hidden == all")
        # marker 口径自检: visible=5 / hidden=2 (fixture 确定性)
        mv = await _db_count(
            f"WHERE created_by_user_id IS NOT NULL AND moderation_status='visible'"
            f" AND reaction_smiles = '{_SMILES}'")
        mh = await _db_count(
            f"WHERE created_by_user_id IS NOT NULL AND moderation_status='hidden'"
            f" AND reaction_smiles = '{_SMILES}'")
        self.assertEqual(self.MARKER_VISIBLE, mv)
        self.assertEqual(self.MARKER_HIDDEN, mh)

    async def test_r4_param_boundaries(self):
        code, _ = await _call_admin("/admin/reactions?limit=101", 0)
        self.assertEqual(422, code)
        code, _ = await _call_admin("/admin/reactions?limit=50&offset=-1", 0)
        self.assertEqual(422, code)


def asyncio_run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else __import__("asyncio").run(coro)


if __name__ == "__main__":
    unittest.main()
