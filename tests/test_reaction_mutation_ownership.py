"""E3 — Reaction Update/Delete Application Ownership 契约测试。

覆盖(任务书 §Tests + Architecture gate):
- owner update success / unauthorized / admin / system-import / participants
  replacement / rollback on relationship failure
- delete success / unauthorized / statistics 副作用
- public-visible invariant(moderated/public 区分)
- HTTP 精确 status/detail 契约(PUT/DELETE)
- adapter 零 domain transaction、service 唯一 owner、service 无 transport import、
  adapter 内零重复 SQL 业务实现

本文件全部不依赖 DB(打桩 service 协作者 + AST 结构锁); 真库链路(行锁/并发/
落库/级联/统计落值)由 tests/test_reaction_mutation_ownership_db.py 覆盖。
"""

from __future__ import annotations

import ast
import inspect
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import HTTPException

from api import reactions as adapter
from api.schemas.reactions import ParticipantBody, ReactionBody
from api.services import reactions as service


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeRow:
    """最小 Row 替身: 支持下标 + 真值(非空行为真, 与原 `if not current` 一致)。"""

    def __init__(self, *vals):
        self._vals = list(vals)

    def __getitem__(self, i):
        return self._vals[i]


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class RecordingDB:
    """记录语句顺序的 session 替身; 可选在匹配子串处抛错。"""

    def __init__(self, row=None, fail_on: str | None = None):
        self.statements: list[tuple[str, str]] = []
        self.commits = 0
        self.rollbacks = 0
        self._row = row
        self._fail_on = fail_on

    async def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        if "FOR UPDATE" in flat:
            self.statements.append(("select_for_update", flat))
            return FakeResult(self._row)
        if self._fail_on and self._fail_on in flat:
            raise RuntimeError(f"injected failure: {self._fail_on}")
        self.statements.append(("sql", flat))
        return FakeResult(None)

    async def commit(self):
        self.statements.append(("commit", ""))
        self.commits += 1

    async def rollback(self):
        self.statements.append(("rollback", ""))
        self.rollbacks += 1

    def kinds(self):
        return [k for k, _ in self.statements]

    def sqls(self):
        return [s for k, s in self.statements if k == "sql"]

    def mutations(self):
        return [s for s in self.sqls() if s.startswith(("UPDATE", "DELETE", "INSERT"))]


class FakeActor:
    def __init__(self, actor_id=7, auth_kind="session", role="member"):
        self.id = actor_id
        self.auth_kind = auth_kind
        self.role = role


def _async_none(*_a, **_k):
    async def _run():
        return None
    return _run()


def _async_ret(value):
    async def _run():
        return value
    return _run()


def _body(visibility: str = "public") -> ReactionBody:
    """与 production contract 同 shape 的请求体(真 ReactionBody/ParticipantBody)。

    E3: service 的 canonical_participants 直接消费 ParticipantBody 契约
    (item.smiles / item.role / item.model_dump()), 测试不得用 dict 替身。
    """
    return ReactionBody(
        visibility=visibility,
        source_type="self",
        participants=[
            ParticipantBody(role="REACTANT", smiles="CCO"),
            ParticipantBody(role="PRODUCT", smiles="CCO"),
        ],
    )


class _Harness:
    """把 service 的所有协作者打成记录器, 只留被验证的业务序。"""

    def __init__(self, db: RecordingDB, skip: set[str] | None = None):
        self.db = db
        self.skip = set(skip or ())
        self.events: list[str] = []
        self.relationships: list[tuple] = []
        self.notifies: list[tuple] = []

    def __enter__(self):
        self._stack = ExitStack()

        async def _enforce(bucket, identity, limit, window):
            self.events.append("enforce")

        async def _resolve(dbcore, participants):
            self.events.append("resolve_participants")
            return [{"role": "REACTANT", "smiles": "CCO"}], []

        async def _write_relationships(dbcore, reaction_id, resolved):
            self.events.append("write_relationships")
            self.relationships.append((reaction_id, tuple(resolved)))

        async def _notify(dbcore, actor_id, reaction_id):
            self.events.append("notify")

        async def _response(dbcore, reaction_id, created):
            self.events.append("reaction_response")
            return {"id": reaction_id, "created_chemical_ids": list(created)}

        def _canonical(body):
            self.events.append("canonical_participants")
            return ([{"role": "REACTANT", "smiles": "CCO"}], "CCO>>CCO")

        def _values(body):
            self.events.append("reaction_values")
            return {"visibility": body.visibility}

        for name, repl in (
            ("enforce", _enforce),
            ("resolve_participants", _resolve),
            ("write_relationships", _write_relationships),
            ("notify_new_reaction_safely", _notify),
            ("reaction_response", _response),
            ("canonical_participants", _canonical),
            ("reaction_values", _values),
        ):
            if name in self.skip:
                continue
            self._stack.enter_context(patch.object(service, name, repl))
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)


# ---------------------------------------------------------------------------
# 1. update: 业务序 / 统计副作用 / 中性错误
# ---------------------------------------------------------------------------

class UpdateServiceOwnershipTests(unittest.IsolatedAsyncioTestCase):

    async def _update(self, row=FakeRow(7, "public", "visible"), visibility="public",
                      fail_on=None, actor_id=7, auth_kind="session"):
        db = RecordingDB(row=row, fail_on=fail_on)
        with _Harness(db) as h:
            result = await service.update_reaction(
                db, actor_id=actor_id, auth_kind=auth_kind, reaction_id=5,
                body=_body(visibility=visibility))
        return db, h, result

    async def test_owner_update_success_order_and_commit(self):
        db, h, result = await self._update(visibility="private")
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        # 行锁在最前, commit 在最后
        self.assertEqual(db.kinds()[0], "select_for_update")
        self.assertEqual(db.kinds()[-1], "commit")
        # 业务序: 行锁 → kernel → resolve → UPDATE row → 关系替换 → 统计
        self.assertEqual(h.events, [
            "enforce", "canonical_participants", "resolve_participants",
            "reaction_values", "write_relationships", "reaction_response"])
        muts = db.mutations()
        self.assertTrue(muts[0].startswith("UPDATE chemistry.reactions SET"))
        self.assertTrue(any(m.startswith("DELETE FROM chemistry.reaction_chemicals")
                            for m in muts))
        self.assertEqual(result["id"], 5)

    async def test_participants_replacement_deletes_then_rewrites(self):
        db, h, _ = await self._update()
        mutations = db.mutations()
        self.assertTrue(mutations[0].startswith("UPDATE chemistry.reactions SET"))
        self.assertTrue(mutations[1].startswith("DELETE FROM chemistry.reaction_chemicals"))
        # 关系替换发生在 commit 之前、且只写一次
        self.assertEqual(len(h.relationships), 1)
        self.assertEqual(h.relationships[0][0], 5)
        self.assertLess(db.kinds().index("commit"),
                        len(db.kinds()))

    async def test_public_to_private_decrements_statistics_and_unfollows(self):
        db, _, _ = await self._update(row=FakeRow(7, "public", "visible"),
                                      visibility="private")
        sqls = " || ".join(db.sqls())
        self.assertIn("DELETE FROM community.reaction_follows", sqls)
        self.assertIn("exact_count=greatest(exact_count-1,0)", sqls)

    async def test_private_to_public_increments_statistics(self):
        db, h, _ = await self._update(row=FakeRow(7, "private", "visible"),
                                      visibility="public")
        sqls = " || ".join(db.sqls())
        self.assertIn("exact_count=exact_count+1", sqls)
        self.assertNotIn("DELETE FROM community.reaction_follows", sqls)
        # 私有 → 公开: commit 之后才通知
        self.assertIn("notify", h.events)
        self.assertEqual(h.events.index("notify"), len(h.events) - 2)

    async def test_no_notify_when_visibility_unchanged(self):
        _, h, _ = await self._update(row=FakeRow(7, "public", "visible"),
                                     visibility="public")
        self.assertNotIn("notify", h.events)

    async def test_public_visible_invariant_hidden_row_has_no_statistics_effect(self):
        """moderated/public 区分: public+hidden → private 不动统计。"""
        db, _, _ = await self._update(row=FakeRow(7, "public", "hidden"),
                                      visibility="private")
        sqls = " || ".join(db.sqls())
        self.assertNotIn("chemistry.statistics", sqls)
        self.assertIn("DELETE FROM community.reaction_follows", sqls)

    async def test_public_to_public_touches_no_statistics(self):
        db, _, _ = await self._update(row=FakeRow(7, "public", "visible"),
                                      visibility="public")
        sqls = " || ".join(db.sqls())
        self.assertNotIn("chemistry.statistics", sqls)
        self.assertNotIn("community.reaction_follows", sqls)

    async def test_system_import_row_is_not_owner_for_update(self):
        """system-import: created_by_user_id IS NULL → 403 只能维护自己创建的反应。"""
        db = RecordingDB(row=FakeRow(None, "public", "visible"))
        with _Harness(db):
            with self.assertRaises(service.ReactionAccessError) as ctx:
                await service.update_reaction(
                    db, actor_id=7, auth_kind="session", reaction_id=5,
                    body=_body())
        self.assertEqual(ctx.exception.kind, service.ReactionAccessError.NOT_OWNER)
        self.assertEqual(ctx.exception.detail, "只能维护自己创建的反应")
        self.assertEqual(db.mutations(), [])
        self.assertEqual(db.commits, 0)

    async def test_relationship_failure_rolls_back_without_commit(self):
        db = RecordingDB(row=FakeRow(7, "public", "visible"))

        async def _boom(dbcore, reaction_id, resolved):
            raise RuntimeError("relationship write failed")

        with _Harness(db, skip={"write_relationships"}):
            with patch.object(service, "write_relationships", _boom):
                with self.assertRaises(RuntimeError):
                    await service.update_reaction(
                        db, actor_id=7, auth_kind="session", reaction_id=5,
                        body=_body(visibility="public"))
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)
        # 关系失败前已发的 UPDATE 未落库(rollback 是最后一条)
        self.assertEqual(db.kinds()[-1], "rollback")

    async def test_not_found_is_neutral(self):
        db = RecordingDB(row=None)
        with _Harness(db):
            with self.assertRaises(service.ReactionAccessError) as ctx:
                await service.update_reaction(
                    db, actor_id=7, auth_kind="session", reaction_id=5,
                    body=_body())
        self.assertEqual(ctx.exception.kind, service.ReactionAccessError.NOT_FOUND)
        self.assertEqual(ctx.exception.detail, "反应不存在")
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.mutations(), [])

    async def test_agent_forbidden_before_any_db_work(self):
        db = RecordingDB(row=FakeRow(7, "public", "visible"))
        with _Harness(db):
            with self.assertRaises(service.AgentReactionMutationForbiddenError) as ctx:
                await service.update_reaction(
                    db, actor_id=7, auth_kind="agent", reaction_id=5,
                    body=_body())
        self.assertEqual(ctx.exception.detail,
                         "API Token 当前不开放反应编辑，请使用网页登录会话")
        self.assertEqual(db.statements, [])

    async def test_update_has_no_admin_bypass(self):
        """admin 非 owner 与普通用户同待遇(迁移前后一致)。"""
        db = RecordingDB(row=FakeRow(7, "public", "visible"))
        with _Harness(db):
            with self.assertRaises(service.ReactionAccessError) as ctx:
                await service.update_reaction(
                    db, actor_id=9, auth_kind="session", reaction_id=5,
                    body=_body())
        self.assertEqual(ctx.exception.kind, service.ReactionAccessError.NOT_OWNER)
        self.assertEqual(ctx.exception.detail, "只能维护自己创建的反应")
        self.assertEqual(db.mutations(), [])


# ---------------------------------------------------------------------------
# 2. delete: 业务序 / 统计副作用 / 中性错误
# ---------------------------------------------------------------------------

class DeleteServiceOwnershipTests(unittest.IsolatedAsyncioTestCase):

    async def _delete(self, row=FakeRow(7, "public", "visible"), actor_id=7,
                      auth_kind="session"):
        db = RecordingDB(row=row)
        with _Harness(db):
            result = await service.delete_reaction(
                db, actor_id=actor_id, auth_kind=auth_kind, reaction_id=5)
        return db, result

    async def test_delete_success_statistics_and_commit(self):
        db, result = await self._delete()
        self.assertIsNone(result)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(db.kinds(), ["select_for_update", "sql", "sql", "commit"])
        self.assertTrue(db.sqls()[0].startswith("DELETE FROM chemistry.reactions WHERE"))
        self.assertIn("exact_count=greatest(exact_count-1,0)", db.sqls()[1])

    async def test_delete_public_hidden_has_no_statistics_effect(self):
        db, _ = await self._delete(row=FakeRow(7, "public", "hidden"))
        self.assertEqual(len(db.mutations()), 1)
        self.assertNotIn("chemistry.statistics", " ".join(db.sqls()))

    async def test_delete_private_visible_has_no_statistics_effect(self):
        db, _ = await self._delete(row=FakeRow(7, "private", "visible"))
        self.assertNotIn("chemistry.statistics", " ".join(db.sqls()))

    async def test_delete_unauthorized_owner_mismatch(self):
        db = RecordingDB(row=FakeRow(7, "public", "visible"))
        with _Harness(db):
            with self.assertRaises(service.ReactionAccessError) as ctx:
                await service.delete_reaction(
                    db, actor_id=9, auth_kind="session", reaction_id=5)
        self.assertEqual(ctx.exception.kind,
                         service.ReactionAccessError.DELETE_NOT_OWNER)
        self.assertEqual(ctx.exception.detail, "只能删除自己创建的反应")
        self.assertEqual(db.mutations(), [])
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    async def test_delete_system_import_row_forbidden(self):
        db = RecordingDB(row=FakeRow(None, "public", "visible"))
        with _Harness(db):
            with self.assertRaises(service.ReactionAccessError) as ctx:
                await service.delete_reaction(
                    db, actor_id=7, auth_kind="session", reaction_id=5)
        self.assertEqual(ctx.exception.kind,
                         service.ReactionAccessError.SYSTEM_IMPORT)
        self.assertEqual(ctx.exception.detail, "系统导入反应不能由用户删除")
        self.assertEqual(db.mutations(), [])

    async def test_delete_not_found(self):
        db = RecordingDB(row=None)
        with _Harness(db):
            with self.assertRaises(service.ReactionAccessError) as ctx:
                await service.delete_reaction(
                    db, actor_id=7, auth_kind="session", reaction_id=5)
        self.assertEqual(ctx.exception.kind, service.ReactionAccessError.NOT_FOUND)
        self.assertEqual(ctx.exception.detail, "反应不存在")

    async def test_delete_agent_forbidden_before_any_db_work(self):
        db = RecordingDB(row=FakeRow(7, "public", "visible"))
        with _Harness(db):
            with self.assertRaises(service.AgentReactionMutationForbiddenError) as ctx:
                await service.delete_reaction(
                    db, actor_id=7, auth_kind="agent", reaction_id=5)
        self.assertEqual(ctx.exception.detail,
                         "API Token 当前不开放反应删除，请使用网页登录会话")
        self.assertEqual(db.statements, [])

    async def test_delete_has_no_rate_limit(self):
        """delete 迁移前后均无限流; 未新增。"""
        self.assertNotIn("enforce(", inspect.getsource(service.delete_reaction))
        self.assertNotIn("RateLimitError", inspect.getsource(adapter.delete_reaction))


# ---------------------------------------------------------------------------
# 3. HTTP 精确 status/detail 契约(adapter 映射)
# ---------------------------------------------------------------------------

class HttpMappingContractTests(unittest.IsolatedAsyncioTestCase):

    def _actor(self, auth_kind="session", actor_id=7):
        return FakeActor(actor_id=actor_id, auth_kind=auth_kind)

    async def _put_expect(self, exc):
        async def _raiser(*_a, **_k):
            raise exc

        with patch.object(adapter, "update_reaction_service", _raiser):
            with self.assertRaises(HTTPException) as ctx:
                await adapter.update_reaction(
                    body=_body(), reaction_id=5, actor=self._actor(),
                    db=RecordingDB())
        return ctx.exception

    async def _delete_expect(self, exc):
        async def _raiser(*_a, **_k):
            raise exc

        with patch.object(adapter, "delete_reaction_service", _raiser):
            with self.assertRaises(HTTPException) as ctx:
                await adapter.delete_reaction(
                    reaction_id=5, actor=self._actor(), db=RecordingDB())
        return ctx.exception

    async def test_put_agent_forbidden_403_exact(self):
        exc = await self._put_expect(service.AgentReactionMutationForbiddenError(
            service.AgentReactionMutationForbiddenError.EDIT_DETAIL))
        self.assertEqual((exc.status_code, exc.detail),
                         (403, "API Token 当前不开放反应编辑，请使用网页登录会话"))

    async def test_delete_agent_forbidden_403_exact(self):
        exc = await self._delete_expect(service.AgentReactionMutationForbiddenError(
            service.AgentReactionMutationForbiddenError.DELETE_DETAIL))
        self.assertEqual((exc.status_code, exc.detail),
                         (403, "API Token 当前不开放反应删除，请使用网页登录会话"))

    async def test_put_not_found_404_exact(self):
        exc = await self._put_expect(service.ReactionAccessError(
            service.ReactionAccessError.NOT_FOUND, "反应不存在"))
        self.assertEqual((exc.status_code, exc.detail), (404, "反应不存在"))

    async def test_put_not_owner_403_exact(self):
        exc = await self._put_expect(service.ReactionAccessError(
            service.ReactionAccessError.NOT_OWNER, "只能维护自己创建的反应"))
        self.assertEqual((exc.status_code, exc.detail),
                         (403, "只能维护自己创建的反应"))

    async def test_delete_not_owner_403_exact(self):
        exc = await self._delete_expect(service.ReactionAccessError(
            service.ReactionAccessError.DELETE_NOT_OWNER, "只能删除自己创建的反应"))
        self.assertEqual((exc.status_code, exc.detail),
                         (403, "只能删除自己创建的反应"))

    async def test_delete_system_import_403_exact(self):
        exc = await self._delete_expect(service.ReactionAccessError(
            service.ReactionAccessError.SYSTEM_IMPORT, "系统导入反应不能由用户删除"))
        self.assertEqual((exc.status_code, exc.detail),
                         (403, "系统导入反应不能由用户删除"))

    async def test_put_delete_not_found_404_exact(self):
        exc = await self._delete_expect(service.ReactionAccessError(
            service.ReactionAccessError.NOT_FOUND, "反应不存在"))
        self.assertEqual((exc.status_code, exc.detail), (404, "反应不存在"))

    async def test_put_validation_400_409_exact(self):
        for kind, status in ((service.ReactionValidationError.INVALID_STRUCTURE, 400),
                             (service.ReactionValidationError.DUPLICATE_PARTICIPANT, 409),
                             (service.ReactionValidationError.INVALID_REACTION, 400)):
            exc = await self._put_expect(
                service.ReactionValidationError(kind, f"detail-{kind}"))
            self.assertEqual((exc.status_code, exc.detail), (status, f"detail-{kind}"))

    async def test_put_rate_limit_429_503_exact(self):
        from api.core.rate_limit import LimiterUnavailable, RateLimited

        exc = await self._put_expect(RateLimited("请求过于频繁，请稍后重试", 5))
        self.assertEqual((exc.status_code, exc.detail),
                         (429, "请求过于频繁，请稍后重试"))
        self.assertEqual(exc.headers.get("Retry-After"), "5")
        self.assertEqual(exc.headers.get("X-RateLimit-Remaining"), "0")

        exc = await self._put_expect(LimiterUnavailable("限流服务不可用，请稍后重试"))
        self.assertEqual(exc.status_code, 503)

    async def test_success_paths_pass_actor_identity_to_service(self):
        calls = {}

        async def _ok(db, **kwargs):
            calls.update(kwargs)
            return {"id": kwargs["reaction_id"]}

        with patch.object(adapter, "update_reaction_service", _ok):
            out = await adapter.update_reaction(
                body=_body(), reaction_id=5, actor=self._actor(actor_id=11),
                db=RecordingDB())
        self.assertEqual(out, {"id": 5})
        self.assertEqual(calls["actor_id"], 11)
        self.assertEqual(calls["auth_kind"], "session")
        self.assertEqual(calls["reaction_id"], 5)

        async def _ok_delete(db, **kwargs):
            calls.clear()
            calls.update(kwargs)
            return None

        with patch.object(adapter, "delete_reaction_service", _ok_delete):
            out = await adapter.delete_reaction(
                reaction_id=6, actor=self._actor(actor_id=12), db=RecordingDB())
        self.assertIsNone(out)
        self.assertEqual(calls, {"actor_id": 12, "auth_kind": "session",
                                 "reaction_id": 6})

    async def test_routes_and_status_codes_unchanged(self):
        """复用 contract-governance 的 route 读取方法(不自造 collector)。"""
        from tests.test_api_contract_governance import _app, _iter_routes

        physical = set(_iter_routes(_app()))
        self.assertIn(("PUT", "/api/reactions/{reaction_id}"), physical)
        self.assertIn(("DELETE", "/api/reactions/{reaction_id}"), physical)
        # status_code 取自 reactions 自己的 APIRoute 对象(E3 未改)
        declared: dict[str, int] = {}
        for route in adapter.router.routes:
            if getattr(route, "path", "").endswith("/reactions/{reaction_id}"):
                for method in route.methods or ():
                    declared[method] = route.status_code
        self.assertEqual(declared.get("DELETE"), 204)
        # FastAPI: 未显式声明 status_code 时 route.status_code is None → 有效 200
        self.assertIn(declared.get("PUT"), (None, 200))
        # 有效对外契约(app 自身 OpenAPI): PUT 200 / DELETE 204
        paths = _app().openapi()["paths"]["/api/reactions/{reaction_id}"]
        self.assertIn("200", paths["put"]["responses"])
        self.assertIn("204", paths["delete"]["responses"])


# ---------------------------------------------------------------------------
# 4. Architecture gate
# ---------------------------------------------------------------------------

_ADAPTER_FORBIDDEN_CALLS = {
    "text", "execute", "commit", "rollback", "enforce", "enforce_http",
    "to_thread", "canonical_participants", "resolve_participants",
    "write_relationships", "reaction_values", "reaction_response",
    "notify_new_reaction_safely", "resolve_or_create_chemical", "flush",
}

_SQL_TOKENS = (
    "FOR UPDATE",
    "UPDATE chemistry.reactions SET",
    "DELETE FROM chemistry.reactions WHERE",
    "DELETE FROM chemistry.reaction_chemicals",
    "UPDATE chemistry.statistics",
)


def _adapter_func(name):
    tree = ast.parse(inspect.getsource(adapter))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in adapter AST")


class ArchitectureGateTests(unittest.TestCase):

    def test_adapter_update_delete_own_zero_domain_transaction(self):
        for name in ("update_reaction", "delete_reaction"):
            node = _adapter_func(name)
            called = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        called.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        called.add(fn.attr)
            leaked = called & _ADAPTER_FORBIDDEN_CALLS
            self.assertEqual(leaked, set(),
                             f"adapter {name} 仍持有事务/业务调用: {leaked}")
            # 无 SQL 字面量
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    for token in _SQL_TOKENS:
                        self.assertNotIn(token, sub.value.upper(),
                                         f"adapter {name} 残留 SQL: {token}")

    def test_fake_request_body_matches_production_participant_contract(self):
        """测试替身 = 真 ReactionBody/ParticipantBody(production shape, 非 dict)。"""
        participants, reaction_smiles = service.canonical_participants(_body())
        self.assertEqual([p["role"] for p in participants],
                         ["REACTANT", "PRODUCT"])
        self.assertEqual(reaction_smiles.count(">"), 2)

    def test_adapter_calls_unique_owner_once(self):
        for name, target in (("update_reaction", "update_reaction_service"),
                             ("delete_reaction", "delete_reaction_service")):
            src = inspect.getsource(getattr(adapter, name))
            self.assertEqual(src.count(target + "("), 1,
                             f"{name} 必须只调用一次 {target}")
            self.assertIn(f"await {target}(", src)

    def test_sql_business_implementation_lives_only_in_service(self):
        """E3 ownership 边界: 只比对 adapter 与 service 两个文件。

        (不得全 api/ 扫描: api/admin.py 的 moderation UPDATE 是范围外合法代码。)
        """
        adapter_src = inspect.getsource(adapter)
        service_src = inspect.getsource(service)
        for token in _SQL_TOKENS:
            self.assertNotIn(token, adapter_src, f"adapter 残留业务 SQL: {token}")
            self.assertIn(token, service_src, f"service 缺失业务 SQL: {token}")
        # adapter 里 update/delete 两个 handler 不得出现任何 SQL 字面量
        for name in ("update_reaction", "delete_reaction"):
            self.assertNotIn("chemistry.", inspect.getsource(getattr(adapter, name)))

    def test_service_update_delete_transport_neutral(self):
        forbidden = {"HTTPException", "ToolError", "Request", "Response", "UploadFile"}
        for name in ("update_reaction", "delete_reaction"):
            tree = ast.parse(inspect.getsource(getattr(service, name)))
            for sub in ast.walk(tree):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        self.assertNotIn(alias.name, forbidden)
                    if isinstance(sub, ast.ImportFrom) and sub.module:
                        self.assertFalse(sub.module.startswith(
                            ("fastapi", "starlette", "mcp")))
                if isinstance(sub, ast.Name):
                    self.assertNotIn(sub.id, forbidden)
                if isinstance(sub, ast.Attribute):
                    self.assertNotIn(sub.attr, forbidden)

    def test_service_owns_row_lock_and_commit_boundary(self):
        for name in ("update_reaction", "delete_reaction"):
            src = inspect.getsource(getattr(service, name))
            self.assertIn("FOR UPDATE", src)
            self.assertIn("await db.commit()", src)
            self.assertIn("await db.rollback()", src)
            # 行锁在 commit 之前
            self.assertLess(src.index("FOR UPDATE"), src.index("await db.commit()"))
            # 通知/响应在 commit 之后(不在事务内)
            if "notify_new_reaction_safely" in src:
                self.assertLess(src.index("await db.commit()"),
                                src.index("notify_new_reaction_safely"))

    def test_predicate_boundary_owner_list_still_owner_filtered(self):
        """list_my_reactions 仍是 owner list(不是 public filter)。"""
        from api.services import reactions as svc

        src = inspect.getsource(svc.list_my_reactions)
        self.assertIn("created_by_user_id", src)
        self.assertNotIn("moderation_status='visible'", src)

    def test_public_access_predicate_not_unified(self):
        """统计用的 public+visible 谓词与列表渲染谓词各自独立(未统一)。"""
        upd = inspect.getsource(service.update_reaction)
        self.assertIn('current[1] == "public" and current[2] == "visible"', upd)
        self.assertIn('current[1] == "private" and current[2] == "visible"', upd)
        dele = inspect.getsource(service.delete_reaction)
        self.assertIn('record[1] == "public" and record[2] == "visible"', dele)
        # 列表渲染谓词仍在 adapter 的 user_reactions, 未被替换为统计谓词
        self.assertIn("moderation_status='visible'",
                      inspect.getsource(adapter.user_reactions))
