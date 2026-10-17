"""CX 批 —— P2 修复的行为锁定测试。

覆盖(与回执 状态表逐项对应):
- F-01: notes 写入限流桶 + 每用户存量上限(NoteQuotaExceededError)
- HGS-SEARCH-LIKE-LITERAL-01: like_literal 转义 + 检索按字面命中
- HGS-SKILL-PATH-01: 连续两点文件名在 zip 校验层被拒(与 DB CHECK 对齐)
- HGS-GATE-HALFOPEN-01: 停档后半开只放行一个探测名额
- HGS-IDENTITY-ERROR-REVIVE-01: pubchem 通道解锁含 pubchem_identity_jobs
- F-06: prune_oauth_credentials 契约(过期/撤销各表清理, 未到期保留)
- P2c-tombstone: 清扫只动 grace 外的 .deleted-* 目录
- notes 超大 ID: int32 上界 → 422(此前 500)
- DOI 双源: 同反应 rx.doi 与 provenance 同 DOI 命中只出一行

运行: TEST_DATABASE_URL=… python -m unittest tests.test_p2c_cx
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip  # noqa: E402
    _RAW = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + _RAW.split("://", 1)[1].split("?", 1)[0]
except Exception:  # pragma: no cover
    DB_URL = None

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

RUN = os.urandom(4).hex()


def _run(coro):
    return asyncio.run(coro)

SKILL_MD = """---
name: CX P2C Literal Path
description: literal path fixture
---

# test
"""


class LikeLiteralUnitTests(unittest.TestCase):
    def test_percent_underscore_backslash_escaped(self):
        from api.core.text import like_literal
        self.assertEqual(like_literal("100%_pure"), "100\\%\\_pure")
        self.assertEqual(like_literal("a\\b"), "a\\\\b")
        self.assertEqual(like_literal("plain"), "plain")

    def test_search_module_consumes_literal_escape(self):
        """检索三层的 LIKE 输入统一走 like_literal(源码锁)。"""
        import api.services.search as s
        src = open(s.__file__, encoding="utf-8").read()
        self.assertIn("like_literal(query)", src)
        self.assertIn("like_literal(nq)", src)
        self.assertNotIn("ILIKE '%' || :q || '%'\", {\"q\": query", src)


class SkillPathZipTests(unittest.TestCase):
    def _zip_bytes(self, name: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("SKILL.md", SKILL_MD)
            z.writestr(name, "x")
        return buf.getvalue()

    def test_consecutive_dots_rejected_like_db_check(self):
        from api.services.skills import (
            SkillArchiveValidationError, extract_skill_zip,
        )
        for name in ("guide..md", "docs/a..b.txt", "a...b"):
            with self.subTest(name=name):
                with self.assertRaises(SkillArchiveValidationError):
                    extract_skill_zip(self._zip_bytes(name))

    def test_single_dot_names_still_pass(self):
        from api.services.skills import extract_skill_zip
        manifest = extract_skill_zip(self._zip_bytes("guide.md"))
        self.assertIn("file_count", manifest)



class _StubRedis:
    """gate_halfopen_admit 所需的最小 redis 语义(get/set nx/delete)。"""

    def __init__(self, data: dict | None = None):
        self.data = dict(data or {})

    async def get(self, k):
        return self.data.get(k)

    async def incr(self, k):
        v = int(self.data.get(k, 0)) + 1
        self.data[k] = str(v)
        return v

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.data:
            return None
        self.data[k] = v
        return True

    async def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)
        return len(keys)


class GateHalfOpenUnitTests(unittest.TestCase):
    def test_stop_ladder_single_probe_then_blocked(self):
        from api.services.gate import gate_halfopen_admit
        r = _StubRedis({"gate:pubchem:streak": "9"})
        # 第一个请求拿到唯一探测名额, 派发收敛为 1
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 1)
        # 积压下的后续请求全部让位等待
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 0)
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 0)

    def test_below_stop_ladder_dispatch_unchanged(self):
        from api.services.gate import gate_halfopen_admit
        for streak in (None, "5", "8"):
            r = _StubRedis({"gate:pubchem:streak": streak} if streak else {})
            self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 4)

    def test_success_clears_probe_for_next_window(self):
        from api.services.gate import gate_record_success, gate_halfopen_admit
        r = _StubRedis({"gate:pubchem:streak": "9"})
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 1)
        _run(gate_record_success(r, "pubchem"))
        # streak 清零 → 正常派发
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 4)

    def test_error_clears_probe_marker(self):
        from api.services.gate import gate_record_error, gate_halfopen_admit
        r = _StubRedis({"gate:pubchem:streak": "9"})
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 1)
        _run(gate_record_error(r, "pubchem"))
        # 探测失败 → 新静默窗 + 探测标记已清(下个半开窗可重新拿名额)
        self.assertNotIn("gate:pubchem:probe", r.data)
        r.data.pop("gate:pubchem:silent_until", None)
        self.assertEqual(_run(gate_halfopen_admit(r, "pubchem", 4)), 1)


class TombstoneSweepTests(unittest.TestCase):
    def test_only_stale_deleted_dirs_removed(self):
        import tempfile
        import time
        from pathlib import Path
        from scripts.sweep_skill_tombstones import sweep
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / ".deleted-1-old"
            fresh = root / ".deleted-2-new"
            canonical = root / "3"
            other = root / "docs"
            for d in (stale, fresh, canonical, other):
                d.mkdir()
                (d / "f.txt").write_text("x")
            old_ts = time.time() - 8 * 86400
            os.utime(stale, (old_ts, old_ts))
            out = sweep(root, grace_days=7, dry_run=False)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(canonical.exists())
            self.assertTrue(other.exists())
            self.assertEqual((out["candidates"], out["deleted"], out["kept_fresh"]),
                             (2, 1, 1))

    def test_dry_run_removes_nothing(self):
        import tempfile
        import time
        from pathlib import Path
        from scripts.sweep_skill_tombstones import sweep
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / ".deleted-9-old"
            stale.mkdir()
            (stale / "f").write_text("x")
            old_ts = time.time() - 8 * 86400
            os.utime(stale, (old_ts, old_ts))
            out = sweep(root, grace_days=7, dry_run=True)
            self.assertTrue(stale.exists())
            self.assertEqual(out["deleted"], 0)
            self.assertEqual(out["candidates"], 1)


@unittest.skipIf(DB_URL is None, "no test DB")
class DbP2cTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        cls.engine = create_async_engine(DB_URL, poolclass=NullPool)

    @classmethod
    def tearDownClass(cls):
        _run(cls.engine.dispose())

    def _q(self, sql, **params):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                rows = (await db.execute(text(sql), params)).mappings().all()
                return [dict(r) for r in rows]
        return _run(go())

    def _exec(self, sql, **params):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                await db.execute(text(sql), params)
        return _run(go())

    def test_gate_unlock_revives_identity_error_rows(self):
        from api.services.gate import gate_unlock_error_rows

        async def go():
            from sqlalchemy import text
            async with self.engine.begin() as db:
                chem = (await db.execute(text(
                    "INSERT INTO chemistry.chemicals (preferred_name)"
                    " VALUES (:n) RETURNING id"),
                    {"n": f"cxg-{RUN}"})).scalar()
                j1 = (await db.execute(text("""
                    INSERT INTO maintenance.pubchem_identity_jobs
                      (chemical_id,evidence_type,evidence_value,evidence_hash,
                       status,priority,dedupe_key)
                    VALUES (:c,'inchikey',:ev,:eh,'error',50,:dk)
                    RETURNING id
                """), {"c": chem, "ev": f"ik-{RUN}", "eh": RUN,
                       "dk": f"cxg-{RUN}-1"})).scalar()
                j2 = (await db.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs
                      (chemical_id,query_value,status,dedupe_key)
                    VALUES (:c,:qv,'error',:dk)
                    RETURNING id
                """), {"c": chem, "qv": "1", "dk": f"cxg-{RUN}-2"})).scalar()
                await gate_unlock_error_rows(db, "pubchem")
                s1 = (await db.execute(text(
                    "SELECT status FROM maintenance.pubchem_identity_jobs WHERE id=:i"
                ), {"i": j1})).scalar()
                s2 = (await db.execute(text(
                    "SELECT status FROM maintenance.pubchem_jobs WHERE id=:i"
                ), {"i": j2})).scalar()
                await db.execute(text(
                    "DELETE FROM maintenance.pubchem_identity_jobs WHERE id=:i"
                ), {"i": j1})
                await db.execute(text(
                    "DELETE FROM maintenance.pubchem_jobs WHERE id=:i"
                ), {"i": j2})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id=:c"), {"c": chem})
                return s1, s2
        s1, s2 = _run(go())
        self.assertEqual((s1, s2), ("queued", "queued"),
                         "通道解锁必须连 pubchem_identity_jobs 一起复活"
                         "(HGS-IDENTITY-ERROR-REVIVE-01)")

    def test_note_quota_exceeded(self):
        from api.services.notes import NoteQuotaExceededError, create_note
        from api.core import config as cfg

        async def go():
            from sqlalchemy import text
            async with self.engine.begin() as db:
                u = (await db.execute(text("""
                    INSERT INTO community.users (username, display_name, email,
                        password_hash, role, status, created_at)
                    VALUES (:u, 'CX', :e, 'x', 'member', 'active', now())
                    RETURNING id
                """), {"u": f"cxq{RUN}", "e": f"cxq{RUN}@x.io"})).scalar()
                n = (await db.execute(text("""
                    SELECT count(*) FROM community.notes WHERE owner_user_id=:u
                """), {"u": u})).scalar()
                return u, int(n)
        user_id, count = _run(go())
        old = cfg.settings.api_note_max_per_user
        cfg.settings.api_note_max_per_user = count  # 已存量=上限 → 下一次必撞
        try:
            async def attempt():
                from unittest.mock import patch

                async def _noop(*a, **k):
                    return None
                # 限流走真 redis(db15)会随窗口抖动 — 单测只锁存量上限语义,
                # 限流桶另由契约面覆盖; 此处 patch 掉 enforce。
                with patch("api.core.rate_limit.enforce", _noop):
                    async with self.engine.begin() as db:
                        await create_note(db, actor_id=user_id, visibility="private",
                                          content="quota", chemical_ids=[],
                                          reaction_ids=[])
            with self.assertRaises(NoteQuotaExceededError):
                _run(attempt())
        finally:
            cfg.settings.api_note_max_per_user = old
        self._exec("DELETE FROM community.notes WHERE owner_user_id=:u", u=user_id)
        self._exec("DELETE FROM community.users WHERE id=:u", u=user_id)

    def test_notes_oversized_id_is_422_not_500(self):
        # 只挂 notes router 的最小 app: 不触发 api.main 的 MCP session manager
        # (TestClient(app) 的 lifespan 会让全局 manager 二次 run 报错)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.notes import router as notes_router
        app = FastAPI()
        app.include_router(notes_router, prefix="/api")
        with TestClient(app) as client:
            r = client.get("/api/notes/99999999999999999999")
        self.assertEqual(r.status_code, 422,
                         "超大 ID 必须 422(此前穿到 SQL 撞 DataError 500)")

    def test_doi_dual_source_single_row(self):
        from api.services.chemicals import InvalidDoiError, reaction_lookup

        async def go():
            from sqlalchemy import text
            async with self.engine.begin() as db:
                doi = f"10.9999/cx-{RUN}"
                rx = (await db.execute(text("""
                    INSERT INTO chemistry.reactions
                      (reaction_smiles, visibility, moderation_status, doi)
                    VALUES ('CCO>>CC(=O)O', 'public', 'visible', :doi)
                    RETURNING id
                """), {"doi": doi})).scalar()
                o = (await db.execute(text("""
                    INSERT INTO ord.reaction (reaction_id) VALUES (:rid)
                    RETURNING id
                """), {"rid": f"cx-{RUN}"})).scalar()
                await db.execute(text(
                    "INSERT INTO ord.reaction_map (reaction_id, ord_reaction_id)"
                    " VALUES (:r, :o)"), {"r": rx, "o": o})
                for _ in range(2):  # 同反应两条同 DOI provenance(双源重复源)
                    await db.execute(text("""
                        INSERT INTO ord.reaction_provenance
                          (ord_schema_context, reaction_id, doi)
                        VALUES ('other', :o, :doi)
                    """), {"o": o, "doi": doi})
                rows = await reaction_lookup(db, f"doi:{doi}", 20, actor_id=None)
                # 清理
                await db.execute(text(
                    "DELETE FROM ord.reaction_provenance WHERE reaction_id=:o"
                ), {"o": o})
                await db.execute(text(
                    "DELETE FROM ord.reaction_map WHERE reaction_id=:r"
                ), {"r": rx})
                await db.execute(text(
                    "DELETE FROM ord.reaction WHERE id=:o"), {"o": o})
                await db.execute(text(
                    "DELETE FROM chemistry.reactions WHERE id=:r"), {"r": rx})
                return rows
        rows = _run(go())
        self.assertEqual(len(rows), 1,
                         "同反应经 rx.doi 与 provenance 双源命中必须去重为单行")

    def test_search_like_literal_percent(self):
        from api.services.search import execute_search

        async def go():
            from sqlalchemy import text
            async with self.engine.begin() as db:
                cid = (await db.execute(text("""
                    INSERT INTO chemistry.chemicals (preferred_name)
                    VALUES (:n) RETURNING id
                """), {"n": f"100% PURE CX {RUN}"})).scalar()
                try:
                    hit = await execute_search(db, f"100% PURE CX {RUN}",
                                               "exact", threshold=0.7,
                                               page=1, page_size=10, actor_id=None)
                    miss = await execute_search(db, f"1000% PURE CX {RUN}",
                                                "exact", threshold=0.7,
                                                page=1, page_size=10, actor_id=None)
                finally:
                    await db.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:c"), {"c": cid})
                return hit, miss
        hit, miss = _run(go())
        hit_ids = [c["id"] for c in (hit.get("chemicals") or [])] if isinstance(hit, dict) else [c.id for c in hit]
        miss_ids = [c["id"] for c in (miss.get("chemicals") or [])] if isinstance(miss, dict) else []
        self.assertEqual(len(hit_ids), 1, "字面 % 查询应命中含 % 的名称")
        self.assertEqual(miss_ids, [], "字面 % 不得放大为通配符匹配其他行")


@unittest.skipIf(DB_URL is None, "no test DB")
class OauthPruneContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        cls.engine = create_async_engine(DB_URL, poolclass=NullPool)

    @classmethod
    def tearDownClass(cls):
        _run(cls.engine.dispose())

    def test_prune_removes_expired_keeps_fresh(self):
        from datetime import datetime, timedelta, timezone
        from scripts.prune_oauth_credentials import prune
        from sqlalchemy.ext.asyncio import async_sessionmaker
        engine = self.engine

        async def go():
            from sqlalchemy import text
            S = async_sessionmaker(engine, expire_on_commit=False)
            old = datetime.now(timezone.utc) - timedelta(days=30)
            fresh = datetime.now(timezone.utc)
            async with S() as db:
                u = (await db.execute(text("""
                    INSERT INTO community.users (username, display_name, email,
                        password_hash, role, status, created_at)
                    VALUES (:u, 'CX', :e, 'x', 'member', 'active', now())
                    RETURNING id
                """), {"u": f"cxo{RUN}", "e": f"cxo{RUN}@x.io"})).scalar()
                # client FK: 注册一个最小 client(20261006_02 oauth_clients)
                cid = (await db.execute(text("""
                    INSERT INTO community.oauth_clients
                      (client_id, client_name, redirect_uris)
                    VALUES (:cid, 'cx-prune', ARRAY['https://a/cb'])
                    ON CONFLICT (client_id) DO NOTHING
                    RETURNING client_id
                """), {"cid": f"cx-prune-{RUN[:6]}"})).scalar() or f"cx-prune-{RUN[:6]}"
                rh = os.urandom(32)
                old_req = (await db.execute(text("""
                    INSERT INTO community.oauth_authorization_requests
                      (request_hash, user_id, client_id, redirect_uri, scopes,
                       state, resource, code_challenge, expires_at)
                    VALUES (:rh, :u, :cid, 'https://a', ARRAY['read'],
                            's', 'res', 'plain', :t)
                    RETURNING id
                """), {"rh": rh, "u": u, "cid": cid, "t": old})).scalar()
                fresh_req = (await db.execute(text("""
                    INSERT INTO community.oauth_authorization_requests
                      (request_hash, user_id, client_id, redirect_uri, scopes,
                       state, resource, code_challenge, expires_at)
                    VALUES (:rh, :u, :cid, 'https://a', ARRAY['read'],
                            's', 'res', 'plain', :t)
                    RETURNING id
                """), {"rh": os.urandom(32), "u": u, "cid": cid,
                       "t": fresh})).scalar()
                revoked_old = (await db.execute(text("""
                    INSERT INTO community.oauth_access_tokens
                      (user_id, client_id, token_hash, scopes, resource,
                       expires_at, revoked_at)
                      VALUES (:u, :cid, :h, ARRAY['read'], 'res', :t, :t2)
                    RETURNING id
                """), {"u": u, "cid": cid, "h": os.urandom(32), "t": fresh,
                       "t2": old})).scalar()
                await db.commit()
            stats = await prune(S, grace_days=7, batch=1000, dry_run=False)
            async with S() as db:
                remain = [int(r[0]) for r in (await db.execute(text("""
                    SELECT id FROM community.oauth_authorization_requests
                    WHERE id = ANY(:ids)
                """), {"ids": [old_req, fresh_req]})).fetchall()]
                tok = (await db.execute(text(
                    "SELECT count(*) FROM community.oauth_access_tokens WHERE id=:i"
                ), {"i": revoked_old})).scalar()
                await db.execute(text(
                    "DELETE FROM community.oauth_authorization_requests"
                    " WHERE user_id=:u"), {"u": u})
                await db.execute(text(
                    "DELETE FROM community.oauth_access_tokens WHERE user_id=:u"
                ), {"u": u})
                await db.execute(text(
                    "DELETE FROM community.oauth_clients WHERE client_id=:cid"
                ), {"cid": cid})
                await db.commit()
                return stats, remain, int(tok), fresh_req
        stats, remain, tok, fresh_req = _run(go())
        self.assertEqual(remain, [fresh_req], "过期 request 删除, 未到期保留")
        self.assertEqual(tok, 0, "撤销超 grace 的 access token 删除")
        self.assertGreater(stats["tables"]
                           ["community.oauth_authorization_requests"]["deleted"], 0)


if __name__ == "__main__":
    unittest.main()
