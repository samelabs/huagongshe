"""凭证管理接口(发放/列表/停用改额度; 令牌只发放一次)。真链测试库。"""

from __future__ import annotations

import re
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ASYNC_URL = None
try:
    from tests.db_gate import test_db_or_skip
    ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://",
                       test_db_or_skip().split("?")[0])
except Exception:
    pass

if ASYNC_URL:
    from api.admin_data_clients import (
        ClientCreateBody, ClientPatchBody, create_client, list_clients, update_client)


class _Actor:
    id = 1
    role = "admin"


def _body(response):
    import json as _json
    return _json.loads(response.body)


@unittest.skipUnless(ASYNC_URL, "测试库闸")
class AdminDataClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.run = uuid.uuid4().hex[:10]
        async with self.Session() as db:
            # 真实管理员用户夹具: created_by 非空, 凭证必须落在具体管理员名下。
            self.owner = (await db.execute(text("""
                INSERT INTO community.users (username,email,password_hash,role,display_name)
                VALUES (:u,:e,'x','admin','数据服务管理员') RETURNING id
            """), {"u": f"dc{self.run}", "e": f"dc{self.run}@t.example"})).scalar()
            await db.commit()
        self.actor = _Actor()
        self.actor.id = self.owner
        self.created: list[int] = []

    async def asyncTearDown(self):
        async with self.Session() as db:
            for pk in self.created:
                await db.execute(text(
                    "DELETE FROM data_api.usage_daily WHERE client_id=:pk"), {"pk": pk})
                await db.execute(text(
                    "DELETE FROM data_api.clients WHERE id=:pk"), {"pk": pk})
            await db.execute(text(
                "DELETE FROM community.users WHERE id=:uid"), {"uid": self.owner})
            await db.commit()
        await self.engine.dispose()

    async def test_create_returns_token_once(self):
        async with self.Session() as db:
            response = await create_client(
                ClientCreateBody(name=f"凭证{uuid.uuid4().hex[:6]}",
                                 contact="zhang@example.com",
                                 scopes=["data:chemical:read"],
                                 rate_per_minute=30, rate_per_day=5000),
                actor=self.actor, db=db)
        self.assertEqual(response.status_code, 201)
        row = _body(response)
        self.created.append(row["id"])
        self.assertTrue(row["token"].startswith("hgsd_"))
        self.assertIn("data:chemical:read", row["scopes"])
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        # 令牌哈希可验证(库里只有哈希)
        from api.services.data_api.auth import token_hash
        async with self.Session() as db:
            stored = (await db.execute(text(
                "SELECT token_hash FROM data_api.clients WHERE id=:pk"),
                {"pk": row["id"]})).scalar()
        self.assertEqual(stored, token_hash(row["token"]))

    async def test_invalid_scope_rejected(self):
        from fastapi import HTTPException
        async with self.Session() as db:
            with self.assertRaises(HTTPException) as ctx:
                await create_client(
                    ClientCreateBody(name="坏凭证", scopes=["data:nonsense"]),
                    actor=self.actor, db=db)
            self.assertEqual(ctx.exception.status_code, 422)

    async def test_list_shows_usage(self):
        async with self.Session() as db:
            response = await create_client(
                ClientCreateBody(name=f"用量{uuid.uuid4().hex[:6]}",
                                 scopes=["data:reaction:read"]),
                actor=self.actor, db=db)
        row = _body(response)
        self.created.append(row["id"])
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO data_api.usage_daily(client_id, day, calls, errors)
                VALUES (:pk, :today, 7, 2)
            """), {"pk": row["id"], "today": date.today()})  # 与计量写入同取进程日期
            await db.commit()
            listing = await list_clients(actor=self.actor, db=db)
        mine = next(item for item in listing["items"] if item["id"] == row["id"])
        self.assertEqual(mine["calls_today"], 7)
        self.assertEqual(mine["errors_today"], 2)
        self.assertNotIn("token", mine)

    async def test_disable_and_reenable(self):
        async with self.Session() as db:
            response = await create_client(
                ClientCreateBody(name=f"停用{uuid.uuid4().hex[:6]}",
                                 scopes=["data:chemical:read"]),
                actor=self.actor, db=db)
        row = _body(response)
        self.created.append(row["id"])
        async with self.Session() as db:
            disabled = await update_client(row["id"], ClientPatchBody(enabled=False),
                                           actor=self.actor, db=db)
            self.assertFalse(disabled["enabled"])
            enabled = await update_client(row["id"], ClientPatchBody(enabled=True),
                                          actor=self.actor, db=db)
            self.assertTrue(enabled["enabled"])


if __name__ == "__main__":
    unittest.main()
