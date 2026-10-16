"""对外数据服务端点的端到端契约(真链测试库 + 测试 Redis, 零外网)。

签名通过/错签/过期/重放/未登记路径/scope 不足/停用凭证、额度(429 与
Retry-After、凭证之间互不影响)、批量上限、已合并 HCID 404、私有反应
不可见、用量记录 —— 逐项锁定。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import unittest
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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

TOKEN = "hgsd_endpoint_test_token"
SECOND_TOKEN = "hgsd_endpoint_second_token"
EXPIRY_TOKEN = "hgsd_endpoint_expiry_token"
INGEST_TOKEN = "hgsd_endpoint_ingest_token"


class FakeHeaders:
    def __init__(self, mapping):
        self._m = {k.lower(): v for k, v in mapping.items()}

    def get(self, key, default=None):
        return self._m.get(key.lower(), default)


class FakeURL:
    def __init__(self, path, query):
        self.path = path
        self.query = query


class FakeRequest:
    def __init__(self, path, query="", headers=None):
        self.method = "GET"
        self.url = FakeURL(path, query)
        self.headers = FakeHeaders(headers or {})
        self._body = b""

    async def body(self):
        return self._body


def signed_headers(token, path, query=""):
    from api.services.data_api.auth import (
        body_sha256_hex, compute_signature, sign_message)

    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = compute_signature(
        token, sign_message("GET", path, query, body_sha256_hex(b""), timestamp, nonce))
    return {
        "authorization": f"Bearer {token}",
        "x-client-id": "",  # 由调用方按凭证填
        "x-timestamp": timestamp,
        "x-nonce": nonce,
        "x-signature": signature,
    }


if ASYNC_URL:
    import api.data_api as data_api
    from api.services.data_api.auth import (
        CHEMICAL_READ_SCOPE, CHEMICAL_INGEST_SCOPE,
        REACTION_READ_SCOPE, token_hash)


@unittest.skipUnless(ASYNC_URL, "测试库闸")
class DataApiEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.run = str(uuid.uuid4().hex[:10])
        self.credentials: list[tuple[str, str, int]] = []
        # 一个保证存在的化合物: 与站内同一规则本地建行。
        from api.services.reactions import resolve_or_create_chemical
        async with self.Session() as db:
            # 真实管理员用户夹具: created_by 非空, 凭证必须落在具体管理员名下。
            self.owner = (await db.execute(text("""
                INSERT INTO community.users (username,email,password_hash,role,display_name)
                VALUES (:u,:e,'x','admin','数据服务管理员') RETURNING id
            """), {"u": f"dp{self.run}", "e": f"dp{self.run}@t.example"})).scalar()
            self.hcid, _ = await resolve_or_create_chemical(db, "CCO")
            await db.commit()
            self.merged_old = int(f"9{uuid.uuid4().hex[:7]}", 16) % 2_000_000_000
            await db.execute(text("""
                INSERT INTO maintenance.chemical_identity_redirect(
                    old_chemical_id, canonical_chemical_id)
                VALUES (:old, :new)
            """), {"old": self.merged_old, "new": self.hcid})
            await db.commit()

    async def asyncTearDown(self):
        async with self.Session() as db:
            for client_id, token, pk in self.credentials:
                await db.execute(text(
                    "DELETE FROM data_api.usage_daily WHERE client_id=:pk"),
                    {"pk": pk})
                await db.execute(text(
                    "DELETE FROM data_api.clients WHERE id=:pk"), {"pk": pk})
            await db.execute(text(
                "DELETE FROM maintenance.chemical_identity_redirect"
                " WHERE old_chemical_id=:old"), {"old": self.merged_old})
            await db.execute(text(
                "DELETE FROM community.users WHERE id=:uid"), {"uid": self.owner})
            await db.commit()
        await self.engine.dispose()

    async def _make_client(self, *, scopes, rate_per_minute=1000, rate_per_day=100000,
                           enabled=True, token=TOKEN):
        client_id = f"hgsd-{self.run}{len(self.credentials)}"
        async with self.Session() as db:
            row = (await db.execute(text("""
                INSERT INTO data_api.clients
                    (client_id, name, contact, scopes, rate_per_minute,
                     rate_per_day, enabled, created_by, token_hash)
                VALUES (:cid, :name, '', CAST(:scopes AS text[]), :rpm, :rpd,
                        :enabled, :owner, :th)
                RETURNING id
            """), {"cid": client_id, "name": f"测试凭证{self.run}",
                   "scopes": scopes, "rpm": rate_per_minute, "rpd": rate_per_day,
                   "enabled": enabled, "owner": self.owner, "th": token_hash(token)})).fetchone()
            await db.commit()
        self.credentials.append((client_id, token, row[0]))
        return client_id

    async def _call(self, endpoint, path, query="", headers=None, db=None):
        import inspect
        from urllib.parse import parse_qs

        request = FakeRequest(path, query, headers)
        kwargs: dict = {}
        # 直调不经 FastAPI 依赖注入: 查询串按端点形参名解析, Query 默认值
        # 展开为其 underlying default; 路径参数从路径尾段解析。
        parsed = parse_qs(query)
        for name, param in inspect.signature(endpoint).parameters.items():
            if name in ("request", "db"):
                continue
            if name in parsed:
                raw = parsed[name][0]
                kwargs[name] = int(raw) if "int" in str(param.annotation) else raw
            elif param.default is not inspect.Signature.empty:
                kwargs.setdefault(name, getattr(param.default, "default", param.default))
        tail = path.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            key = "hrid" if "/reactions/" in path else "hcid"
            kwargs[key] = int(tail)
        elif path.endswith("/reactions"):
            # /chemicals/{hcid}/reactions —— 实体 id 在倒数第二段
            second = path.rstrip("/").rsplit("/", 2)[-2]
            if second.isdigit():
                kwargs.setdefault("hcid", int(second))
        async with (db or self.Session()) as s:
            return await endpoint(request, db=s, **kwargs)

    @staticmethod
    def _status(result) -> int:
        # 成功路径直调返回 dict(=200); 错误路径返回 JSONResponse。
        return 200 if isinstance(result, dict) else result.status_code

    @staticmethod
    def _json(result):
        return result if isinstance(result, dict) else json.loads(result.body)

    def _auth_headers(self, client_id, token, path, query=""):
        headers = signed_headers(token, path, query)
        headers["x-client-id"] = client_id
        return headers

    # ── 签名与凭证 ──────────────────────────────────────────────────

    async def test_valid_signed_request_succeeds(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        path = f"/data/v1/chemicals/{self.hcid}"
        response = await self._call(
            data_api.chemical_detail, path, "locale=zh-CN",
            self._auth_headers(client_id, TOKEN, path, "locale=zh-CN"))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertIn("request_id", payload)
        self.assertEqual(payload["chemical"]["hcid"], self.hcid)
        self.assertEqual(payload["chemical"]["names"]["identifiers"]["pubchem_cid"],
                         payload["chemical"]["names"]["identifiers"]["pubchem_cid"])

    async def test_wrong_signature_rejected(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        headers = self._auth_headers(client_id, TOKEN, f"/data/v1/chemicals/{self.hcid}")
        headers["x-signature"] = "0" * 64
        response = await self._call(
            data_api.chemical_detail, f"/data/v1/chemicals/{self.hcid}", "",
            headers)
        self.assertEqual(self._status(response), 401)
        self.assertEqual(self._json(response)["error"]["code"], "unauthorized")

    async def test_expired_timestamp_rejected(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        path = f"/data/v1/chemicals/{self.hcid}"
        headers = signed_headers(TOKEN, path)
        headers["x-client-id"] = client_id
        headers["x-timestamp"] = str(int(time.time()) - 400)
        from api.services.data_api.auth import (
            body_sha256_hex, compute_signature, sign_message)
        headers["x-signature"] = compute_signature(
            TOKEN, sign_message("GET", path, "", body_sha256_hex(b""),
                                headers["x-timestamp"], headers["x-nonce"]))
        response = await self._call(
            data_api.chemical_detail, path, "", headers)
        self.assertEqual(self._status(response), 401)

    async def test_replayed_nonce_rejected(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        path = f"/data/v1/chemicals/{self.hcid}"
        headers = self._auth_headers(client_id, TOKEN, path)
        first = await self._call(
            data_api.chemical_detail, path, "", dict(headers))
        self.assertEqual(self._status(first), 200)
        second = await self._call(
            data_api.chemical_detail, path, "", dict(headers))
        self.assertEqual(self._status(second), 401)
        self.assertEqual(json.loads(second.body)["error"]["code"], "replayed_request")

    async def test_unregistered_path_refused(self):
        # 反应 scope 的凭证访问化合物详情 → forbidden_scope
        client_id = await self._make_client(scopes=[REACTION_READ_SCOPE])
        path = f"/data/v1/chemicals/{self.hcid}"
        response = await self._call(
            data_api.chemical_detail, path, "",
            self._auth_headers(client_id, TOKEN, path))
        self.assertEqual(self._status(response), 403)
        self.assertEqual(self._json(response)["error"]["code"], "forbidden_scope")

    async def _set_expires(self, client_id, value_sql, params=None):
        from sqlalchemy import text as _t
        async with self.Session() as db:
            await db.execute(_t(
                f"UPDATE data_api.clients SET expires_at={value_sql} "
                "WHERE client_id=:cid"), {"cid": client_id, **(params or {})})
            await db.commit()

    async def test_credential_expiry_three_states(self):
        """到期判断三态（真实 timestamptz 往返）：未到期可用、已到期拒绝、无到期可用。

        历史缺陷：load_client 用 row[6]（datetime）与 time.time()（float）直接
        比较 → TypeError 被外层吞成服务不可用，未到期凭证也无法使用。
        """
        from api.services.data_api.auth import load_client, DataApiAuthError

        # ① 未到期（+1h）：可用
        cid = await self._make_client(scopes=[CHEMICAL_READ_SCOPE], token=EXPIRY_TOKEN)
        await self._set_expires(cid, "now() + interval '1 hour'")
        async with self.Session() as db:
            client = await load_client(db, cid, EXPIRY_TOKEN)
        self.assertEqual(client.client_id, cid)

        # ② 已到期（-1h）：拒绝且报「凭证已到期」
        await self._set_expires(cid, "now() - interval '1 hour'")
        async with self.Session() as db:
            with self.assertRaises(DataApiAuthError) as ctx:
                await load_client(db, cid, EXPIRY_TOKEN)
        self.assertIn("到期", ctx.exception.message)

        # ③ 无到期时间：可用
        await self._set_expires(cid, "NULL")
        async with self.Session() as db:
            client = await load_client(db, cid, EXPIRY_TOKEN)
        self.assertEqual(client.client_id, cid)

    async def test_disabled_credential_rejected(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE], enabled=False)
        path = f"/data/v1/chemicals/{self.hcid}"
        response = await self._call(
            data_api.chemical_detail, path, "",
            self._auth_headers(client_id, TOKEN, path))
        self.assertEqual(self._status(response), 401)

    # ── 额度 ────────────────────────────────────────────────────────

    async def test_quota_exceeded_returns_429_with_retry_after(self):
        client_id = await self._make_client(
            scopes=[CHEMICAL_READ_SCOPE], rate_per_minute=2)
        path = f"/data/v1/chemicals/{self.hcid}"
        statuses = []
        for _ in range(3):
            response = await self._call(
                data_api.chemical_detail, path, "",
                self._auth_headers(client_id, TOKEN, path))
            statuses.append(self._status(response))
        self.assertEqual(statuses, [200, 200, 429])
        # 第 4 个请求仍被拒(Retry-After 头存在)
        response = await self._call(
            data_api.chemical_detail, path, "",
            self._auth_headers(client_id, TOKEN, path))
        self.assertEqual(self._status(response), 429)
        self.assertTrue(response.headers.get("retry-after"))

    async def test_quotas_isolated_between_credentials(self):
        tight = await self._make_client(
            scopes=[CHEMICAL_READ_SCOPE], rate_per_minute=1, token=TOKEN)
        roomy = await self._make_client(
            scopes=[CHEMICAL_READ_SCOPE], rate_per_day=100000, token=SECOND_TOKEN)
        path = f"/data/v1/chemicals/{self.hcid}"
        first = await self._call(
            data_api.chemical_detail, path, "", self._auth_headers(tight, TOKEN, path))
        second = await self._call(
            data_api.chemical_detail, path, "", self._auth_headers(tight, TOKEN, path))
        self.assertEqual([self._status(first), self._status(second)], [200, 429])
        other = await self._call(
            data_api.chemical_detail, path, "",
            self._auth_headers(roomy, SECOND_TOKEN, path))
        self.assertEqual(self._status(other), 200, "凭证之间额度互不影响")

    async def test_usage_recorded_per_day(self):
        client_id, _, pk = None, None, None
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        pk = self.credentials[-1][2]
        path = f"/data/v1/chemicals/{self.hcid}"
        await self._call(data_api.chemical_detail, path, "",
                         self._auth_headers(client_id, TOKEN, path))
        async with self.Session() as db:
            row = (await db.execute(text(
                "SELECT calls, errors FROM data_api.usage_daily WHERE client_id=:pk"),
                {"pk": pk})).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], 0)

    # ── 参数与 404 ──────────────────────────────────────────────────

    async def test_batch_limit_50(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        ids = ",".join(str(self.hcid) for _ in range(51))
        query = f"ids={ids}"
        response = await self._call(
            data_api.chemicals_batch, "/data/v1/chemicals", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals", query))
        self.assertEqual(self._status(response), 422)
        self.assertEqual(self._json(response)["error"]["code"], "invalid_parameter")

    async def test_reaction_batch_limit_20(self):
        client_id = await self._make_client(scopes=[REACTION_READ_SCOPE])
        ids = ",".join("1" for _ in range(21))
        query = f"ids={ids}"
        response = await self._call(
            data_api.reactions_batch, "/data/v1/reactions", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/reactions", query))
        self.assertEqual(self._status(response), 422)

    async def test_merged_hcid_404(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        path = f"/data/v1/chemicals/{self.merged_old}"
        response = await self._call(
            data_api.chemical_detail, path, "",
            self._auth_headers(client_id, TOKEN, path))
        self.assertEqual(self._status(response), 404)
        self.assertEqual(self._json(response)["error"]["code"], "not_found")

    async def test_dual_role_reaction_counted_once(self):
        """同一反应中同一化合物双角色（反应物+产物）：只计一次、不占页位。"""
        async with self.Session() as db:
            owner = (await db.execute(text(
                "SELECT id FROM community.users LIMIT 1"))).scalar()
            rid = (await db.execute(text("""
                INSERT INTO chemistry.reactions
                    (reaction_smiles, visibility, moderation_status,
                     created_by_user_id, source_type)
                VALUES ('A>>A', 'public', 'visible', :owner, 'self')
                RETURNING id
            """), {"owner": owner})).scalar()
            await db.execute(text("""
                INSERT INTO chemistry.reaction_chemicals(
                    reaction_id, chemical_id, role, occurrence_count)
                VALUES (:rid, :cid, 'REACTANT', 1), (:rid, :cid, 'PRODUCT', 1)
            """), {"rid": rid, "cid": self.hcid})
            await db.commit()
        try:
            client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
            path = f"/data/v1/chemicals/{self.hcid}/reactions"
            response = await self._call(
                data_api.chemical_reactions, path, "page=1&page_size=50",
                self._auth_headers(client_id, TOKEN, path, "page=1&page_size=50"))
            self.assertEqual(self._status(response), 200)
            payload = self._json(response)
            ids = [item["hrid"] for item in payload["items"]]
            self.assertEqual(ids.count(rid), 1, "同一反应只能出现一次")
            self.assertEqual(payload["total"], len(set(ids)), "total 为去重后反应数")
        finally:
            async with self.Session() as db:
                await db.execute(text(
                    "DELETE FROM chemistry.reaction_chemicals WHERE reaction_id=:rid"),
                    {"rid": rid})
                await db.execute(text(
                    "DELETE FROM chemistry.reactions WHERE id=:rid"), {"rid": rid})
                await db.commit()

    async def test_private_reaction_invisible(self):
        async with self.Session() as db:
            # 建一条私有反应 + 一条公开反应, 参与物用 setUp 建的化合物。
            owner = (await db.execute(text(
                "SELECT id FROM community.users LIMIT 1"))).scalar()
            private_id = (await db.execute(text("""
                INSERT INTO chemistry.reactions
                    (reaction_smiles, visibility, moderation_status,
                     created_by_user_id, source_type)
                VALUES ('CCO>>CCO', 'private', 'visible', :owner, 'self')
                RETURNING id
            """), {"owner": owner})).scalar()
            public_id = (await db.execute(text("""
                INSERT INTO chemistry.reactions
                    (reaction_smiles, visibility, moderation_status,
                     created_by_user_id, source_type)
                VALUES ('CCO>>CCO', 'public', 'visible', :owner, 'self')
                RETURNING id
            """), {"owner": owner})).scalar()
            await db.execute(text("""
                INSERT INTO chemistry.reaction_chemicals(
                    reaction_id, chemical_id, role, occurrence_count)
                VALUES (:rid, :cid, 'REACTANT', 1)
            """), [{"rid": private_id, "cid": self.hcid},
                   {"rid": public_id, "cid": self.hcid}])
            await db.commit()
        try:
            client_id = await self._make_client(scopes=[REACTION_READ_SCOPE])
            path = f"/data/v1/reactions/{private_id}"
            response = await self._call(
                data_api.reaction_detail, path, "",
                self._auth_headers(client_id, TOKEN, path))
            self.assertEqual(self._status(response), 404)
            path = f"/data/v1/reactions/{public_id}"
            response = await self._call(
                data_api.reaction_detail, path, "",
                self._auth_headers(client_id, TOKEN, path))
            self.assertEqual(self._status(response), 200)
            payload = self._json(response)
            self.assertEqual(payload["reaction"]["hrid"], public_id)
            self.assertEqual(payload["reaction"]["visibility"], "public")
        finally:
            async with self.Session() as db:
                await db.execute(text(
                    "DELETE FROM chemistry.reaction_chemicals"
                    " WHERE reaction_id IN (:a, :b)"),
                    {"a": private_id, "b": public_id})
                await db.execute(text(
                    "DELETE FROM chemistry.reactions WHERE id IN (:a, :b)"),
                    {"a": private_id, "b": public_id})
                await db.commit()

    async def test_readonly_lookup_smiles_miss_writes_nothing(self):
        """只读凭证 lookup 未收录 SMILES：不建行（化合物计数不变）。"""
        from sqlalchemy import text as _t
        async with self.Session() as db:
            before = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemicals"))).scalar_one()
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        query = "smiles=" + "C" * 18 + "O"  # 稀有长链醇, 库内不存在
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["pending"]["status"], "not_found")
        async with self.Session() as db:
            after = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemicals"))).scalar_one()
        self.assertEqual(after, before, "只读凭证不得创建化合物行")

    async def test_readonly_lookup_cas_miss_enqueues_nothing(self):
        """只读凭证 lookup 未收录 CAS：不入列采集（pubchem 任务表不变）。"""
        from sqlalchemy import text as _t
        cas = "99999-77-6"  # 校验位合法(7+14+27+36+45+54+63=246→6)且库内不存在
        async with self.Session() as db:
            before = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemical_pubchem"))).scalar_one()
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        query = f"cas={cas}"
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertEqual(payload["candidates"], [])
        self.assertIn(payload["pending"]["status"], ("not_found", "updating"))
        async with self.Session() as db:
            after = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemical_pubchem"))).scalar_one()
        self.assertEqual(after, before, "只读凭证不得提交采集任务")

    async def test_ingest_scope_lookup_smiles_miss_creates(self):
        """带采集能力位的凭证保持站内规则：未收录 SMILES 建行。"""
        from sqlalchemy import text as _t
        async with self.Session() as db:
            before = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemicals"))).scalar_one()
        client_id = await self._make_client(
            scopes=[CHEMICAL_READ_SCOPE, CHEMICAL_INGEST_SCOPE], token=INGEST_TOKEN)
        # 链长取自 run 标识 → 每轮唯一，重跑不撞已有行
        chain = "C" * (22 + int(self.run[-2], 16) % 6) + "O"
        query = "smiles=" + chain
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, INGEST_TOKEN,
                               "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertTrue(payload["candidates"], "应建行并返回候选")
        self.assertEqual(payload["candidates"][0]["data_status"], "updating")
        async with self.Session() as db:
            after = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemicals"))).scalar_one()
            await db.execute(_t(
                "DELETE FROM chemistry.name_index WHERE chemical_id IN "
                "(SELECT id FROM chemistry.chemicals WHERE smiles=:sm)"),
                {"sm": chain})
            await db.execute(_t(
                "DELETE FROM chemistry.chemical_pubchem WHERE chemical_id IN "
                "(SELECT id FROM chemistry.chemicals WHERE smiles=:sm)"),
                {"sm": chain})
            await db.execute(_t(
                "DELETE FROM chemistry.chemicals WHERE smiles=:sm"), {"sm": chain})
            await db.commit()
        self.assertEqual(after, before + 1)

    async def test_lookup_requires_single_selector(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        query = f"hcid={self.hcid}&cas=64-17-5"
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 422)
        self.assertEqual(self._json(response)["error"]["code"], "invalid_parameter")

    async def test_lookup_by_hcid(self):
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        query = f"hcid={self.hcid}"
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertEqual(payload["candidates"][0]["hcid"], self.hcid)
        self.assertEqual(payload["candidates"][0]["match"], "hcid")


if __name__ == "__main__":
    unittest.main()
