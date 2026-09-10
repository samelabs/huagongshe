"""Resource bounds guards (LOW-PATCH, 2026-09-10)。

只测新增 guard:
1. /users/me/password actor bucket (10/15min) — N 次内允许, 超限 429,
   actor bucket 隔离。
2. MCP render_molecule_svg 直接 smiles 长度上限 4000 (匿名 RDKit 入口)。
不为已有 bounds 写重复矩阵。
"""

from __future__ import annotations

import asyncio
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

OWNER_ID = 3   # tests fixture member (reaction svg 轮已建)
ADMIN_ID = 4   # admin


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
class PasswordChangeRateLimitTests(unittest.TestCase):
    def setUp(self):
        # 模块级 pool(api.core.cache) 绑定 import 后首个 event loop,
        # discover 套跑下前序测试已关 loop → 'Event loop is closed' 503。
        # 本测试自建 pool 替换 rate_limit.pool; pool 必须只在 go() 的
        # 单个 loop 内使用(purge 也在 go() 里, 避免跨 loop 连接)。
        # 纪律: redis 缓存测前 del。
        import redis.asyncio as aioredis
        from api.core import rate_limit

        rate_limit.pool = aioredis.ConnectionPool.from_url(
            os.environ["HGS_REDIS_URL"], decode_responses=True)

    def _change(self, actor_id: int):
        """同步包装: 单独 event loop 跑(注意: api.core.cache 的模块级
        redis pool 绑定首个 loop, 多 loop 复用会 'Event loop is closed' —
        所以全部调用放进同一个 go() 里, 由 test 方法单次 asyncio.run)。"""
        raise NotImplementedError

    def test_password_change_bucket_and_isolation(self):
        import asyncio
        from fastapi import HTTPException
        from api.users import change_password
        from api.core.security import Actor, password_hash
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.pool import NullPool
        from api.schemas.users import PasswordBody

        class _Resp:
            def delete_cookie(self, *a, **k): pass

        # 自建 fixture users(fresh baseline 无历史行, 不依赖 test_hgs 存量)
        import random
        RUN = random.randint(10_000_000, 99_000_000)

        async def _seed_ids(engine):
            async with engine.begin() as db:
                rows = (await db.execute(text("""
                    INSERT INTO community.users
                      (username,email,password_hash,role,display_name)
                    VALUES (:u1,:e1,:p,'member','U'), (:u2,:e2,:p,'admin','A')
                    RETURNING id, role
                """), {"u1": f"utpw{RUN}a", "e1": f"a{RUN}@t.example",
                       "u2": f"utpw{RUN}b", "e2": f"b{RUN}@t.example",
                       "p": await asyncio.to_thread(password_hash, "real0seed")
                       })).fetchall()
            return [r[0] for r in rows]

        engine0 = create_async_engine(DB_URL, poolclass=NullPool)
        try:
            _ids = asyncio.run(_seed_ids(engine0))
        finally:
            asyncio.run(engine0.dispose())
        owner_id, admin_id = _ids
        actors = {owner_id: Actor(id=owner_id, username=f"u{owner_id}", display_name="U",
                                  email=f"a{owner_id}@t.example", role="member",
                                  avatar_path=None, auth_kind="web"),
                  admin_id: Actor(id=admin_id, username=f"u{admin_id}", display_name="A",
                                  email=f"b{admin_id}@t.example", role="admin",
                                  avatar_path=None, auth_kind="web")}
        body = PasswordBody(current_password="wrong0pw",
                            new_password="newpass1A",
                            confirm_password="newpass1A")
        statuses: dict[int, list[int]] = {owner_id: [], admin_id: []}

        async def go():
            import redis.asyncio as aioredis
            r = aioredis.Redis(connection_pool=__import__("api.core.rate_limit", fromlist=["pool"]).pool)
            keys = await r.keys("rate:password-change:*")
            if keys:
                await r.delete(*keys)
            await r.aclose()  # 测前清 bucket(单 loop 内)
            engine = create_async_engine(DB_URL, poolclass=NullPool)
            try:
                async with AsyncSession(engine) as session:
                    for _ in range(10):
                        try:
                            await change_password(
                                body=body, response=_Resp(),
                                actor=actors[owner_id], db=session)
                            statuses[owner_id].append(0)
                        except HTTPException as exc:
                            statuses[owner_id].append(exc.status_code)
                    try:  # 第 11 次 → 429
                        await change_password(body=body, response=_Resp(),
                                              actor=actors[owner_id], db=session)
                        statuses[owner_id].append(0)
                    except HTTPException as exc:
                        statuses[owner_id].append(exc.status_code)
                    try:  # actor 4 隔离 → 400
                        await change_password(body=body, response=_Resp(),
                                              actor=actors[admin_id], db=session)
                        statuses[admin_id].append(0)
                    except HTTPException as exc:
                        statuses[admin_id].append(exc.status_code)
            finally:
                await engine.dispose()

        asyncio.run(go())
        for i, sc in enumerate(statuses[owner_id][:10]):
            self.assertEqual(sc, 400, f"owner 第{i+1}次应 400(密码错误), 非 {sc}")
        self.assertEqual(statuses[owner_id][10], 429, "第 11 次超限须 429")
        self.assertEqual(statuses[admin_id][0], 400, "actor 桶必须隔离")


class McpRenderSmilesBoundTests(unittest.TestCase):
    """512 guard 只管用户直传 smiles; chemical_id(DB) 路径不套用;
    guard 在 RDKit 之前。renderer 全程 mock — 不烧真 CPU。"""

    def _tool(self):
        from api.mcp_server import build_mcp_server
        server = build_mcp_server()
        return next(t for t in server._tool_manager._tools.values()
                    if t.name == "render_molecule_svg")

    def test_direct_513_rejected_before_rdkit(self):
        from mcp.server.mcpserver.exceptions import ToolError
        from api import mol as mol_module

        calls: list[str] = []
        mol_module.smiles_to_svg = lambda *a, **k: calls.append(a[0]) or "<svg/>"
        try:
            with self.assertRaises(ToolError) as raised:
                asyncio.run(self._tool().fn(
                    smiles="C" * 513, width=400, height=300, ctx=None))
            self.assertIn("512", str(raised.exception))
            self.assertEqual(calls, [], "RDKit renderer 不得被调用")
        finally:
            from importlib import reload
            reload(mol_module)

    def test_direct_512_passes_length_guard(self):
        from mcp.server.mcpserver.exceptions import ToolError
        from api import mol as mol_module

        calls: list[str] = []
        mol_module.smiles_to_svg = lambda *a, **k: calls.append(a[0]) or "<svg/>"
        try:
            out = asyncio.run(self._tool().fn(
                smiles="C" * 512, width=400, height=300, ctx=None))
            self.assertEqual(out, "<svg/>")
            self.assertEqual(len(calls), 1, "512 边界值应到达 renderer(mock)")
        finally:
            from importlib import reload
            reload(mol_module)

    def test_chemical_id_path_not_bounded_by_512(self):
        """DB 路径 SMILES(受写入校验)不套 direct-input 512 限制:
        用长 smiles 的库内行验证 renderer 收到完整串。"""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.pool import NullPool
        from sqlalchemy import text
        from api import mol as mol_module
        import random

        calls: list[str] = []
        mol_module.smiles_to_svg = lambda *a, **k: calls.append(a[0]) or "<svg/>"
        long_smiles = "C" * 700
        run = random.randint(10_000_000, 99_000_000)

        from api import mcp_server as mcp_mod
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def go():
            engine = create_async_engine(DB_URL, poolclass=NullPool)
            # chemical_id 路径默认走全局 async_session(app engine, 绑
            # TestClient portal loop) — 测试内替换为自有 engine 的
            # sessionmaker, 避免跨 loop 污染全局连接(殃及 workapi 套跑)
            saved_factory = mcp_mod.async_session
            mcp_mod.async_session = async_sessionmaker(engine,
                                                       expire_on_commit=False)
            try:
                async with engine.begin() as db:
                    cid = (await db.execute(text("""
                        INSERT INTO chemistry.chemicals
                          (preferred_name, smiles)
                        VALUES (:n, :s) RETURNING id
                    """), {"n": f"ut-rb-{run}", "s": long_smiles})).scalar()
                # >512 的 DB smiles: 不受 direct-input 512 guard 限制
                out = await self._tool().fn(
                    chemical_id=cid, width=400, height=300, ctx=None)
                return out
            finally:
                mcp_mod.async_session = saved_factory
                async with engine.begin() as db:
                    await db.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE preferred_name=:n"),
                        {"n": f"ut-rb-{run}"})
                await engine.dispose()

        try:
            out = asyncio.run(go())
            self.assertEqual(out, "<svg/>")
            self.assertEqual(calls, [long_smiles],
                             "DB 路径 SMILES 不受 512 direct-input 限制")
        finally:
            from importlib import reload
            reload(mol_module)


if __name__ == "__main__":
    unittest.main()
