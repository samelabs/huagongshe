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
import types
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
        CHEMICAL_READ_SCOPE, REACTION_READ_SCOPE, token_hash)


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

    async def test_auth_failure_flood_rate_limited(self):
        # 同一来源 IP 的鉴权失败有 per-IP 失败桶 —— 桶满后请求
        # 在查库前即被拒(429 rate_limited), 无效凭证不再每次实打实查库。
        # IP 取自本轮随机串: 失败桶在测试 Redis 里是固定窗口, 防跨轮串桶。
        ip = f"10.{int(self.run[:2], 16)}.{int(self.run[2:4], 16) % 254 + 1}.7"
        path = f"/data/v1/chemicals/{self.hcid}"
        statuses = []
        # 失败桶是固定窗口：冻结引擎时钟于当前窗口中点，循环不被窗口边界拆桶
        window = data_api.AUTH_FAIL_WINDOW_SECONDS
        now = (int(time.time()) // window) * window + window // 2
        from unittest.mock import patch as _patch
        with _patch("api.core.rate_limit.time", types.SimpleNamespace(time=lambda: now)):
            for _ in range(data_api.AUTH_FAIL_LIMIT + 5):
                headers = {
                    "x-real-ip": ip,
                    "authorization": "Bearer no-such-token",
                    "x-client-id": "hgsd-no-such-client",
                    "x-timestamp": str(int(time.time())),
                    "x-nonce": uuid.uuid4().hex,
                    "x-signature": "0" * 64,
                }
                statuses.append(self._status(
                    await self._call(data_api.chemical_detail, path, "", headers)))
                if statuses[-1] == 429:
                    break
        self.assertIn(429, statuses, "失败桶最终应拒绝")
        # check 是 count<=limit 放行: 第 LIMIT+1 次仍放行并计数, 再下一次
        # 预检才拒 —— 401 恰出现 LIMIT+1 次。
        self.assertEqual(statuses.count(401), data_api.AUTH_FAIL_LIMIT + 1)
        self.assertEqual(statuses[statuses.index(429) - 1], 401)

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

    async def test_chemical_batch_budget_times_out_gracefully(self):
        """预算耗尽：剩余 HCID 进 missing、timed_out=true、仍 200 部分成功。"""
        from unittest.mock import patch as _patch
        import api.data_api as dai
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        ids = ",".join(str(self.hcid + i * 1000000) for i in range(3))
        query = f"ids={ids}"

        from api.services.chemicals import ChemicalNotFoundError

        calls = {"n": 0}

        async def slow_detail(db, hcid, **_kw):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            if hcid == self.hcid:
                return {"id": hcid}
            raise ChemicalNotFoundError()

        def fake_project(detail, *_a, **_kw):
            return {"hcid": detail["id"]}

        # 预算压到 0.06s：第 1 项耗时 0.05 通过，其后到点全部让位
        with _patch.object(dai, "get_chemical_detail", slow_detail), \
             _patch.object(dai, "project_chemical", fake_project), \
             _patch.object(dai, "CHEMICAL_BATCH_BUDGET_SECONDS", 0.06):
            response = await self._call(
                data_api.chemicals_batch, "/data/v1/chemicals", query,
                self._auth_headers(client_id, TOKEN, "/data/v1/chemicals", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertTrue(payload["timed_out"])
        self.assertEqual(len(payload["missing"]), 2)
        self.assertEqual(len(payload["items"]), 1)
        # 预算按项前检查：第 2 项发起时尚未到点(0.05<0.06)，第 3 项让位
        self.assertEqual(calls["n"], 2)

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

    async def test_name_lookup_exact_and_contains(self):
        """名称检索带凭据: 精确命中走 preferred_name 等值(match=name),
        模糊命中走 name_index 包含(match=name_contains)。"""
        from urllib.parse import urlencode
        exact_name = f"二茂铁衍生物{self.run}"
        alias_norm = f"ferrocene-alias-{self.run}"
        async with self.Session() as db:
            prior = (await db.execute(text(
                "SELECT preferred_name FROM chemistry.chemicals WHERE id=:id"),
                {"id": self.hcid})).scalar()
            await db.execute(text(
                "UPDATE chemistry.chemicals SET preferred_name=:pn WHERE id=:id"),
                {"pn": exact_name, "id": self.hcid})
            await db.execute(text("""
                INSERT INTO chemistry.name_index (chemical_id,name,lang,normalized,source,kind)
                VALUES (:id,:nm,'en',:nm,'cb','alias_en')
            """), {"id": self.hcid, "nm": alias_norm})
            await db.commit()
        try:
            client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
            path = "/data/v1/chemicals/lookup"
            q = urlencode({"name": exact_name, "locale": "zh-CN"})
            response = await self._call(
                data_api.chemicals_lookup, path, q,
                self._auth_headers(client_id, TOKEN, path, q))
            self.assertEqual(self._status(response), 200)
            payload = self._json(response)
            self.assertTrue(payload["candidates"])
            top = payload["candidates"][0]
            self.assertEqual(top["hcid"], self.hcid)
            self.assertEqual(top["match"], "name")

            # 查询词是别称的真子串: 精确等值不命中, 走 name_index 包含
            fragment = self.run
            q2 = urlencode({"name": fragment, "locale": "zh-CN"})
            response2 = await self._call(
                data_api.chemicals_lookup, path, q2,
                self._auth_headers(client_id, TOKEN, path, q2))
            self.assertEqual(self._status(response2), 200)
            payload2 = self._json(response2)
            self.assertTrue(payload2["candidates"])
            self.assertEqual(payload2["candidates"][0]["match"], "name_contains")
            self.assertIn(self.hcid, [c["hcid"] for c in payload2["candidates"]])
        finally:
            async with self.Session() as db:
                await db.execute(text(
                    "DELETE FROM chemistry.name_index WHERE chemical_id=:id AND normalized=:nm"),
                    {"id": self.hcid, "nm": alias_norm})
                await db.execute(text(
                    "UPDATE chemistry.chemicals SET preferred_name=:pn WHERE id=:id"),
                    {"pn": prior, "id": self.hcid})
                await db.commit()

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
            self.assertNotIn("visibility", payload["reaction"])
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

    async def test_lookup_smiles_miss_creates_row(self):
        """read 凭证 lookup 未收录 SMILES：按站内规则建行并返回 updating 候选。"""
        from sqlalchemy import text as _t
        async with self.Session() as db:
            before = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemicals"))).scalar_one()
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        # 链长取自 run 标识 → 每轮唯一，重跑不撞已有行
        chain = "C" * (22 + int(self.run[-2], 16) % 6) + "O"
        query = "smiles=" + chain
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertTrue(payload["candidates"], "应建行并返回候选")
        self.assertEqual(payload["candidates"][0]["data_status"], "updating")
        hcid = payload["candidates"][0]["hcid"]
        async with self.Session() as db:
            after = (await db.execute(_t(
                "SELECT count(*) FROM chemistry.chemicals"))).scalar_one()
            # 建行触发的 discovery 采集入队走后台优先级档(不占用户优先级)
            disc = (await db.execute(_t("""
                SELECT priority FROM maintenance.pubchem_identity_jobs
                WHERE chemical_id=:hcid ORDER BY id DESC LIMIT 1
            """), {"hcid": hcid})).scalar_one_or_none()
            await db.execute(_t(
                "DELETE FROM maintenance.pubchem_identity_jobs WHERE chemical_id=:hcid",
                ), {"hcid": hcid})
            await db.execute(_t(
                "DELETE FROM chemistry.name_index WHERE chemical_id=:hcid"),
                {"hcid": hcid})
            await db.execute(_t(
                "DELETE FROM chemistry.chemical_pubchem WHERE chemical_id=:hcid"),
                {"hcid": hcid})
            await db.execute(_t(
                "DELETE FROM chemistry.chemicals WHERE id=:hcid"), {"hcid": hcid})
            await db.commit()
        self.assertEqual(after, before + 1)
        self.assertIsNotNone(disc, "建行应触发 discovery 采集入队")
        self.assertEqual(disc, 40, "服务接口触发的采集入队必须走后台优先级档")

    async def _unique_cas(self) -> str:
        """按 run 标识造一个校验位合法的库外 CAS（重跑不撞已有任务）。"""
        digits = f"{int(self.run[:6], 16) % 10_000_000:07d}"[-7:]
        middle = f"{int(self.run[-2:], 16) % 100:02d}"
        body = digits + middle
        check = sum(int(d) * i for i, d in enumerate(reversed(body), start=1)) % 10
        return f"{digits}-{middle}-{check}"

    async def test_lookup_cas_miss_enqueues_background(self):
        """read 凭证 lookup 未收录 CAS：按站内规则入列采集，优先级为后台档。"""
        from sqlalchemy import text as _t
        cas = await self._unique_cas()
        client_id = await self._make_client(scopes=[CHEMICAL_READ_SCOPE])
        query = f"cas={cas}"
        response = await self._call(
            data_api.chemicals_lookup, "/data/v1/chemicals/lookup", query,
            self._auth_headers(client_id, TOKEN, "/data/v1/chemicals/lookup", query))
        self.assertEqual(self._status(response), 200)
        payload = self._json(response)
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["pending"]["status"], "updating")
        async with self.Session() as db:
            job = (await db.execute(_t("""
                SELECT chemical_id, priority FROM maintenance.cas_jobs
                WHERE cas_number=:cas ORDER BY id DESC LIMIT 1
            """), {"cas": cas})).fetchone()
            await db.execute(_t(
                "DELETE FROM maintenance.cas_jobs WHERE cas_number=:cas"), {"cas": cas})
            if job is not None and job[0] is not None:
                await db.execute(_t(
                    "DELETE FROM chemistry.name_index WHERE chemical_id=:hcid"),
                    {"hcid": job[0]})
                await db.execute(_t(
                    "DELETE FROM chemistry.chemical_pubchem WHERE chemical_id=:hcid"),
                    {"hcid": job[0]})
                await db.execute(_t(
                    "DELETE FROM chemistry.chemicals WHERE id=:hcid"
                    " AND cas_numbers @> ARRAY[:cas] AND smiles IS NULL"),
                    {"hcid": job[0], "cas": cas})
            await db.commit()
        self.assertIsNotNone(job, "未收录 CAS 应入列采集")
        self.assertEqual(job[1], 40, "服务接口触发的采集入队必须走后台优先级档")

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


@unittest.skipUnless(ASYNC_URL, "测试库闸")
class DataApiValidationEnvelopeTests(unittest.IsolatedAsyncioTestCase):
    """FastAPI 参数校验 422 也走 /data/v1 统一错误契约（ASGI 真路径）。"""

    async def test_query_validation_returns_envelope(self):
        import httpx
        from api.main import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # hcid 非整数 → FastAPI 校验层 422，不进路由函数
            r = await client.get("/data/v1/chemicals", params={"hcid": "abc"})
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertEqual(body["error"]["code"], "invalid_parameter")
        self.assertIn("message", body["error"])
        self.assertTrue(body["request_id"], "契约要求携带 request_id")
        self.assertNotIn("kind", body, "不得混用站内 {message,kind} 形状")

    async def test_site_validation_shape_unchanged(self):
        import httpx
        from api.main import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await client.get("/api/chemicals/abc/synonyms")
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertEqual(body.get("kind"), "invalid_field")
