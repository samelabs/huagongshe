""" — 已合并旧 HCID 的公开 404 契约(专项, 不做重定向)。

现行absorb 物理删除旧行后, 旧 HCID 在所有公开面一律 404;
maintenance.chemical_identity_redirect 仅供内部任务寻址(canonicalize_id),
公开查询不跟随。本测试在存在 redirect 行的前提下锁定三个公开面:

1. 详情编排 get_chemical_detail(old) → ChemicalNotFoundError
   (HTTP /chemicals/{id} 与 MCP get_chemical 共用此编排, 均 404/工具错误);
2. HTTP 详情 adapter 映射 404 chemical_not_found;
3. 结构图 /mol/{old}/svg → 404 chemical_not_renderable。

真链测试库 + 一次性 redirect 哨兵行(不建化合物, 生产数据零接触)。
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

if ASYNC_URL:
    from fastapi import HTTPException
    import api.mol as mol_api
    import api.routes as routes_api
    from api.services.chemicals import ChemicalNotFoundError, get_chemical_detail


@unittest.skipUnless(ASYNC_URL, "测试库闸")
class MergedHcid404Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        # 高位哨兵 id 段: old 不存在化合物行, 只有 redirect 行。
        self.old_id = int(f"9{uuid.uuid4().hex[:8]}", 16) % 2_000_000_000
        self.new_id = self.old_id + 1
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO maintenance.chemical_identity_redirect(
                    old_chemical_id, canonical_chemical_id)
                VALUES (:old, :new)
            """), {"old": self.old_id, "new": self.new_id})
            await db.commit()

    async def asyncTearDown(self):
        async with self.Session() as db:
            await db.execute(text(
                "DELETE FROM maintenance.chemical_identity_redirect"
                " WHERE old_chemical_id=:old"), {"old": self.old_id})
            await db.commit()
        await self.engine.dispose()

    async def test_detail_orchestration_404_not_redirect(self):
        async with self.Session() as db:
            with self.assertRaises(ChemicalNotFoundError):
                await get_chemical_detail(db, self.old_id,
                                          actor_id=None, priority=50,
                                          enrich="core")

    async def test_http_detail_adapter_maps_404(self):
        async with self.Session() as db:
            with self.assertRaises(HTTPException) as raised:
                await routes_api.chemical_detail(
                    self.old_id, enrich="core", locale=None,
                    actor=None, db=db)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["kind"], "chemical_not_found")

    async def test_structure_svg_404(self):
        async with self.Session() as db:
            with self.assertRaises(HTTPException) as raised:
                await mol_api.render_molecule(
                    chemical_id=self.old_id, w=300, h=300,
                    actor=None, db=db)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["kind"],
                         "chemical_not_renderable")


if __name__ == "__main__":
    unittest.main()
