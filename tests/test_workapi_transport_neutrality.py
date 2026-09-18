"""E5 — WorkAPI transport neutrality: service neutral error ↔ adapter HTTP 映射。

锁(逐条对应 E5 任务书 Tests 段):
- ``api/services/workqueue.py`` / ``api/services/discovery.py``: AST 级零
  fastapi/starlette import; 无 HTTPException/ToolError/Request/Response 等
  transport 符号(注释不计入 — 只扫 AST 节点)
- 两个 service 模块在 **fastapi 不可 import** 的解释器里仍可 import 并抛
  neutral 错误(subprocess 真隔离证明, 不是 grep 假绿)
- ``LeaseConflictError`` = 语义 kind + 逐字 detail; 无 HTTP 属性; 非
  HTTPException 子类 → 非 HTTP 调用方(MCP/脚本)可直接捕获
- ``verified_lease`` / ``verified_cas_lease`` / ``complete_discovery`` 独立于
  HTTP adapter 抛 neutral(hermetic stub db, 零 HTTP 参与)
- adapter 独占 status/detail 映射: complete / cas complete / error /
  cas heartbeat / cas error / identity complete 六条路径 → 逐字 409 + 原文 detail
- adapter 只捕获 intended neutral error: 非预期异常原样传播, 不 catch-all 成 409
- receipt 幂等 ack 分支未漂移(同 worker+token 重试仍 200 idempotent)
- WorkAPI route/scope 契约未变

HTTP 层逐字断言(真实 app + test_hgs)在 tests/test_worker_trusted_plane.py
E5 段; 本模块不做 DB 依赖, 无 TEST_DATABASE_URL 也能全绿。
"""

from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import api.workapi as wa
from api.schemas.workapi import (
    CasCompleteBody, CompleteBody, ErrorBody, IdentityCompleteBody, LeaseProof,
)
from api.services import discovery as dsc
from api.services import workqueue as wq
from api.services.workqueue import LeaseConflictError
from api.workapi import WorkerContext

REPO = Path(__file__).resolve().parents[1]
SERVICE_MODULES = ("api/services/workqueue.py", "api/services/discovery.py")

LEASE_DETAIL = "lease is missing, expired, or owned by another worker"
IDENTITY_DETAIL = "identity job is not leased"

# service 层禁止出现的 transport 符号(AST 级; 只扫 import/Name/Attribute)
BANNED_SYMBOLS = {
    "fastapi", "starlette", "HTTPException", "ToolError",
    "Request", "Response", "StreamingResponse", "UploadFile",
    "JSONResponse", "PlainTextResponse", "APIRouter", "Depends",
}

TOKEN = "t" * 40
WORKER = WorkerContext(worker_id="e5-worker", max_lease_jobs=2)


# ─────────────────────────── helpers ───────────────────────────

class _StubResult:
    """SQLAlchemy Result 最小替身: 恒 '无行'。"""

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def scalar(self):
        return None


class _StubDB:
    """只记账的 db 替身 — 断言 handler 的 commit/rollback 语义未被 E5 改动。"""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.statements: list[str] = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        return _StubResult()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _run(coro):
    return asyncio.run(coro)


async def _raise(exc):
    raise exc


def _src_of(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _ast_of(rel: str) -> ast.Module:
    return ast.parse(_src_of(rel))


def _service_symbols(tree: ast.Module) -> set[str]:
    """收集模块内出现的 transport 相关符号(import 名 + Name + Attribute)。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


# ─────────────────────────── A. import neutrality ───────────────────────────

class ServiceImportNeutralityTests(unittest.TestCase):
    """service 模块不得 import / 引用任何 transport 框架符号(AST 级)。"""

    def test_service_modules_have_no_transport_symbols(self) -> None:
        for rel in SERVICE_MODULES:
            with self.subTest(module=rel):
                found = _service_symbols(_ast_of(rel)) & BANNED_SYMBOLS
                self.assertEqual(
                    found, set(),
                    f"{rel} 仍含 transport 符号: {sorted(found)}")

    def test_service_modules_import_no_fastapi_or_starlette(self) -> None:
        for rel in SERVICE_MODULES:
            with self.subTest(module=rel):
                tree = _ast_of(rel)
                roots: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots.update(a.name.split(".")[0] for a in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        roots.add(node.module.split(".")[0])
                self.assertNotIn("fastapi", roots, rel)
                self.assertNotIn("starlette", roots, rel)

    def test_service_modules_expose_no_httpexception_attribute(self) -> None:
        for mod in (wq, dsc):
            self.assertFalse(hasattr(mod, "HTTPException"), mod.__name__)

    def test_services_importable_with_fastapi_unavailable(self) -> None:
        """真隔离证明: 屏蔽 fastapi/starlette 后仍可 import + 抛 neutral。

        这是 service 不再依赖 transport 的硬证据(grep 之外的运行期验证)。
        """
        code = (
            "import sys\n"
            "for _n in ('fastapi', 'starlette'):\n"
            "    sys.modules[_n] = None\n"
            "import api.services.workqueue as w\n"
            "import api.services.discovery as d\n"
            "assert w.LeaseConflictError.kind == 'lease_conflict'\n"
            "exc = w.LeaseConflictError('x')\n"
            "assert exc.detail == 'x' and str(exc) == 'x'\n"
            "assert not hasattr(exc, 'status_code')\n"
            "print('NEUTRAL_IMPORT_OK')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=str(REPO),
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO)})
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("NEUTRAL_IMPORT_OK", proc.stdout)


# ─────────────────────────── B. neutral error 契约 ───────────────────────────

class NeutralErrorContractTests(unittest.TestCase):
    """neutral 类型: 语义 kind + 逐字 detail, 无 HTTP 属性, 独立于 adapter 可抛。"""

    def test_lease_conflict_error_carries_semantic_kind_and_detail(self) -> None:
        exc = LeaseConflictError(LEASE_DETAIL)
        self.assertEqual(exc.kind, "lease_conflict")
        self.assertEqual(exc.detail, LEASE_DETAIL)
        self.assertEqual(str(exc), LEASE_DETAIL)

    def test_lease_conflict_error_is_not_an_httpexception(self) -> None:
        exc = LeaseConflictError(LEASE_DETAIL)
        self.assertNotIsInstance(exc, HTTPException)
        self.assertFalse(issubclass(LeaseConflictError, HTTPException))
        self.assertFalse(hasattr(exc, "status_code"))
        self.assertFalse(hasattr(exc, "headers"))

    def test_verified_lease_raises_neutral_with_exact_detail(self) -> None:
        db = _StubDB()
        proof = LeaseProof(job_id=1, lease_token=TOKEN)
        with self.assertRaises(LeaseConflictError) as ctx:
            _run(wq.verified_lease(db, proof, WORKER.worker_id))
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        self.assertEqual(ctx.exception.kind, "lease_conflict")
        # 该路径零 DB 写入、零 commit(neutral 化未移动事务边界)
        self.assertEqual(db.commits, 0)

    def test_verified_cas_lease_raises_neutral_with_exact_detail(self) -> None:
        db = _StubDB()
        proof = LeaseProof(job_id=1, lease_token=TOKEN)
        with self.assertRaises(LeaseConflictError) as ctx:
            _run(wq.verified_cas_lease(db, proof, WORKER.worker_id))
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        self.assertEqual(db.commits, 0)

    def test_complete_discovery_raises_neutral_with_exact_detail(self) -> None:
        """discovery 同类泄漏: 未 leased 的 identity job → neutral(非 HTTP)。"""
        db = _StubDB()
        with self.assertRaises(LeaseConflictError) as ctx:
            _run(dsc.complete_discovery(db, job_id=1, cid_list=[]))
        self.assertEqual(ctx.exception.detail, IDENTITY_DETAIL)
        self.assertEqual(ctx.exception.kind, "lease_conflict")

    def test_lease_conflict_is_catchable_without_http_layer(self) -> None:
        """非 HTTP 调用方(MCP/脚本)只 import service 即可捕获。"""
        caught = None
        try:
            _run(wq.verified_lease(
                _StubDB(), LeaseProof(job_id=1, lease_token=TOKEN), "w"))
        except LeaseConflictError as exc:  # 无 fastapi 参与
            caught = exc
        self.assertIsNotNone(caught)
        self.assertEqual(caught.detail, LEASE_DETAIL)


# ─────────────────────────── C. adapter 映射 ───────────────────────────

class AdapterMappingTests(unittest.TestCase):
    """adapter 独占 neutral → HTTP 映射; 逐字 status/detail; 只捕获 intended 类型。"""

    def _patch_conflict(self, name: str) -> None:
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(wa, name, lambda *a, **k: _raise(LeaseConflictError(LEASE_DETAIL))).start()

    def test_mapping_helper_preserves_detail_verbatim(self) -> None:
        out = wa._lease_conflict_http(LeaseConflictError(LEASE_DETAIL))
        self.assertIsInstance(out, HTTPException)
        self.assertEqual(out.status_code, 409)
        self.assertEqual(out.detail, LEASE_DETAIL)

    def test_mapping_helper_is_the_only_409_source_for_neutral(self) -> None:
        """service 抛出的 neutral 不会自带 status — 409 只能由 adapter 决定。"""
        exc = LeaseConflictError(IDENTITY_DETAIL)
        self.assertFalse(hasattr(exc, "status_code"))
        self.assertEqual(wa._lease_conflict_http(exc).status_code, 409)

    def test_complete_job_maps_neutral_to_exact_409(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_lease")
        mock.patch.object(wa, "find_completion_receipt",
                          lambda *a, **k: _none()).start()
        body = CompleteBody(job_id=1, lease_token=TOKEN, result={})
        with self.assertRaises(HTTPException) as ctx:
            _run(wa.complete_job(body=body, db=db, worker=WORKER))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        # E5 前该路径(HTTPException 直穿)不 rollback — 事务语义未移动
        self.assertEqual(db.rollbacks, 0)

    def test_complete_job_receipt_retry_still_idempotent(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_lease")
        mock.patch.object(wa, "find_completion_receipt",
                          lambda *a, **k: _receipt()).start()
        body = CompleteBody(job_id=1, lease_token=TOKEN, result={})
        out = _run(wa.complete_job(body=body, db=db, worker=WORKER))
        self.assertEqual(out, {"status": "ok", "idempotent": True})
        self.assertEqual(db.rollbacks, 0)

    def test_cas_complete_job_maps_neutral_to_exact_409(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_cas_lease")
        mock.patch.object(wa, "find_completion_receipt",
                          lambda *a, **k: _none()).start()
        body = CasCompleteBody(job_id=1, lease_token=TOKEN,
                               result={"status": "not_found"})
        with self.assertRaises(HTTPException) as ctx:
            _run(wa.cas_complete_job(body=body, db=db, worker=WORKER))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        self.assertEqual(db.rollbacks, 0)

    def test_cas_complete_job_receipt_retry_still_idempotent(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_cas_lease")
        mock.patch.object(wa, "find_completion_receipt",
                          lambda *a, **k: _receipt()).start()
        body = CasCompleteBody(job_id=1, lease_token=TOKEN,
                               result={"status": "not_found"})
        out = _run(wa.cas_complete_job(body=body, db=db, worker=WORKER))
        self.assertEqual(out, {"status": "ok", "idempotent": True})

    def test_error_job_maps_neutral_to_exact_409_with_rollback(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_lease")
        body = ErrorBody(job_id=1, lease_token=TOKEN, error_code="E",
                         error_detail="d")
        with self.assertRaises(HTTPException) as ctx:
            _run(wa.error_job(body=body, db=db, worker=WORKER))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        # E5 前该路径由 `except Exception` 兜(rollback 后重抛) — 语义逐字保留
        self.assertEqual(db.rollbacks, 1)

    def test_cas_heartbeat_maps_neutral_to_exact_409_with_rollback(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_cas_lease")
        body = LeaseProof(job_id=1, lease_token=TOKEN)
        with self.assertRaises(HTTPException) as ctx:
            _run(wa.cas_heartbeat(body=body, db=db, worker=WORKER))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        self.assertEqual(db.rollbacks, 1)

    def test_cas_error_job_maps_neutral_to_exact_409_with_rollback(self) -> None:
        db = _StubDB()
        self._patch_conflict("verified_cas_lease")
        body = ErrorBody(job_id=1, lease_token=TOKEN, error_code="E",
                         error_detail="d")
        with self.assertRaises(HTTPException) as ctx:
            _run(wa.cas_error_job(body=body, db=db, worker=WORKER))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, LEASE_DETAIL)
        self.assertEqual(db.rollbacks, 1)

    def test_identity_complete_maps_discovery_neutral_to_exact_409(self) -> None:
        """discovery service 的 neutral 冲突 → 同一 409 映射(不再落 500)。"""
        db = _StubDB()
        mock.patch.object(wa, "_verified_identity_lease",
                          lambda *a, **k: _row()).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(dsc, "complete_discovery",
                          lambda *a, **k: _raise(LeaseConflictError(IDENTITY_DETAIL))).start()
        body = IdentityCompleteBody(job_id=1, lease_token=TOKEN, cid_list=[])
        with self.assertRaises(HTTPException) as ctx:
            _run(wa.complete_identity_job(body=body, db=db, worker=WORKER))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, IDENTITY_DETAIL)

    def test_unexpected_service_error_is_not_converted_to_409(self) -> None:
        """非预期异常按既有行为传播(禁止 catch-all 成 409)。"""
        cases = (
            ("complete_job", "verified_lease",
             CompleteBody(job_id=1, lease_token=TOKEN, result={})),
            ("cas_complete_job", "verified_cas_lease",
             CasCompleteBody(job_id=1, lease_token=TOKEN,
                             result={"status": "not_found"})),
            ("error_job", "verified_lease",
             ErrorBody(job_id=1, lease_token=TOKEN, error_code="E", error_detail="d")),
            ("cas_heartbeat", "verified_cas_lease",
             LeaseProof(job_id=1, lease_token=TOKEN)),
            ("cas_error_job", "verified_cas_lease",
             ErrorBody(job_id=1, lease_token=TOKEN, error_code="E", error_detail="d")),
        )
        for handler_name, service_name, body in cases:
            with self.subTest(handler=handler_name):
                db = _StubDB()
                # 用 with 保证 patch 一定回收(跨模块泄漏会让后续 DB 测试全 500)
                with mock.patch.object(wa, service_name,
                                       lambda *a, **k: _raise(RuntimeError("boom"))):
                    with self.assertRaises(RuntimeError) as ctx:
                        _run(getattr(wa, handler_name)(
                            body=body, db=db, worker=WORKER))
                    self.assertNotIsInstance(ctx.exception, HTTPException)

    def test_unexpected_discovery_error_is_not_converted_to_409(self) -> None:
        db = _StubDB()
        with mock.patch.object(wa, "_verified_identity_lease",
                               lambda *a, **k: _row()):
            with mock.patch.object(dsc, "complete_discovery",
                                   lambda *a, **k: _raise(RuntimeError("boom"))):
                body = IdentityCompleteBody(job_id=1, lease_token=TOKEN, cid_list=[])
                with self.assertRaises(RuntimeError):
                    _run(wa.complete_identity_job(body=body, db=db, worker=WORKER))

    def test_no_except_all_clause_builds_409(self) -> None:
        """结构闸门: `except Exception` 子句内不得构造 HTTPException(409, ...)。"""
        tree = _ast_of("api/workapi.py")
        offenders: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not _is_broad_exception(handler.type):
                    continue
                for sub in ast.walk(handler):
                    if not isinstance(sub, ast.Raise) or sub.exc is None:
                        continue
                    call = sub.exc
                    if (isinstance(call, ast.Call)
                            and _attr_name(call.func) == "HTTPException"
                            and call.args
                            and isinstance(call.args[0], ast.Constant)
                            and call.args[0].value == 409):
                        offenders.append(sub.lineno)
        self.assertEqual(offenders, [],
                         f"catch-all 子句里出现 409 构造: lines {offenders}")

    def test_neutral_errors_are_caught_by_exact_type_only(self) -> None:
        """六个映射点必须显式 `except LeaseConflictError`(AST 计数)。"""
        tree = _ast_of("api/workapi.py")
        caught = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if _attr_name(handler.type) == "LeaseConflictError":
                    caught += 1
        self.assertEqual(caught, 6,
                         "期望 6 个显式 neutral 捕获点(complete/cas complete/"
                         "error/heartbeat/cas error/identity complete)")


# ─────────────────────────── D. route 契约 ───────────────────────────

class WorkApiRouteContractTests(unittest.TestCase):
    """既有 WorkAPI route/scope 契约未变(E5 不动 state machine / 路由)。"""

    EXPECTED_SCOPE = {
        ("POST", "/workapi/v1/jobs/lease"): "pubchem",
        ("POST", "/workapi/v1/jobs/complete"): "pubchem",
        ("POST", "/workapi/v1/jobs/error"): "pubchem",
        ("POST", "/workapi/v1/cas/jobs/lease"): "cas",
        ("POST", "/workapi/v1/cas/jobs/heartbeat"): "cas",
        ("POST", "/workapi/v1/cas/jobs/complete"): "cas",
        ("POST", "/workapi/v1/cas/jobs/error"): "cas",
        ("POST", "/workapi/v1/identity/jobs/lease"): "pubchem",
        ("POST", "/workapi/v1/identity/jobs/complete"): "pubchem",
        ("POST", "/workapi/v1/identity/jobs/error"): "pubchem",
    }

    def test_route_scope_matrix_unchanged(self) -> None:
        self.assertEqual(wa.ROUTE_SCOPE, self.EXPECTED_SCOPE)

    def test_router_paths_unchanged(self) -> None:
        paths = {r.path for r in wa.router.routes}
        self.assertEqual(paths, {p for _, p in self.EXPECTED_SCOPE})
        methods = {tuple(sorted(r.methods)) for r in wa.router.routes}
        self.assertEqual(methods, {("POST",)})


# ─────────────────────────── 小工具(延后定义便于阅读) ───────────────────────────

async def _none():
    return None


async def _receipt():
    return {"worker_id": WORKER.worker_id, "terminal_status": "ok"}


async def _row():
    return (1, 420042, "ev")


def _is_broad_exception(node) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in ("Exception", "BaseException")
    return False


def _attr_name(node) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


if __name__ == "__main__":
    unittest.main()
