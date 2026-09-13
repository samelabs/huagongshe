"""Batch 1 (admin-list-contracts): users/reactions 列表契约验收测试。

契约 (本轮正式统一, 不保留旧裸数组 shape):
  GET /admin/users?q=&limit=&offset=      -> {"total": N, "items": [...]}
  GET /admin/reactions?status=&limit=&offset= -> {"total": N, "items": [...]}

审计纠偏口径 (必须锁住):
  users 默认列表只能浏览最近 limit 个; 老用户不是绝对不可达 ——
  q 会对全表过滤。正确表述: older users are not reachable through
  list browsing beyond the first page (不是 never accessible)。

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


async def _seed_users(n: int) -> list[int]:
    """造 n 个 marker 用户 (旧 id 区间在前), 返回 ids。清理由 _cleanup 负责。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    eng = create_async_engine(DB_URL)
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
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    eng = create_async_engine(DB_URL)
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as db:
            for uid in ids:
                await db.execute(text("DELETE FROM community.users WHERE id=:i"), {"i": uid})
            await db.commit()
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
    """U1-U4: users 分页/total/search nuance/参数边界。"""

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

    测试库 reactions 总量 293 (其中 user-reactions 288, visible 192, hidden 96),
    直接对全量断言窗口与口径, 不另造 reaction fixture。
    """

    async def test_r1_offset_window_stable(self):
        code, w1 = await _call_admin("/admin/reactions?limit=50&offset=0", 0)
        self.assertEqual(200, code)
        self.assertEqual(50, len(w1["items"]))
        code, w2 = await _call_admin("/admin/reactions?limit=50&offset=50", 0)
        self.assertEqual(200, code)
        ids1 = [r["id"] for r in w1["items"]]
        ids2 = [r["id"] for r in w2["items"]]
        self.assertFalse(set(ids1) & set(ids2), "窗口不得重叠")
        self.assertEqual(ids1, sorted(ids1, reverse=True), "ORDER BY id DESC")

    async def test_r2_total_excludes_system_rows(self):
        """R2: status=all 的 total 必须只含 created_by_user_id IS NOT NULL。"""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        eng = create_async_engine(DB_URL)
        try:
            async with async_sessionmaker(eng)() as db:
                expect = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reactions WHERE created_by_user_id IS NOT NULL"
                ))).scalar_one()
        finally:
            await eng.dispose()
        code, body = await _call_admin("/admin/reactions?status=all&limit=1", 0)
        self.assertEqual(200, code)
        self.assertEqual(expect, body["total"])
        self.assertLess(len(body["items"]), body["total"], "total > len(items) (limit=1)")

    async def test_r3_status_filter_total_same_set(self):
        """R3: visible/hidden 的 total 与 items 同一过滤集合; visible+hidden=all。"""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        eng = create_async_engine(DB_URL)
        try:
            async with async_sessionmaker(eng)() as db:
                exp_v = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reactions "
                    "WHERE created_by_user_id IS NOT NULL AND moderation_status='visible'"
                ))).scalar_one()
                exp_h = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reactions "
                    "WHERE created_by_user_id IS NOT NULL AND moderation_status='hidden'"
                ))).scalar_one()
        finally:
            await eng.dispose()
        code, v = await _call_admin("/admin/reactions?status=visible&limit=1", 0)
        code2, h = await _call_admin("/admin/reactions?status=hidden&limit=1", 0)
        self.assertEqual(200, code); self.assertEqual(200, code2)
        self.assertEqual(exp_v, v["total"])
        self.assertEqual(exp_h, h["total"])
        code, a = await _call_admin("/admin/reactions?status=all&limit=1", 0)
        self.assertEqual(exp_v + exp_h, a["total"], "visible + hidden == all")

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
