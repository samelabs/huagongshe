"""MCP / AI 接入治理契约测试(batch: fix/mcp-15-governance)。

只锁结构与语义契约, 不做大段文案 snapshot:
- MCP tool surface = 13(E9-B 删 get_chemical_externals);
- get_skill slug 解析按可访问候选集, 歧义 fail-closed, 不泄露不可访问技能;
- numeric skill_id 不走 slug resolver;
- REST / MCP validate_skill 统一 skill:write;
- MCP product version = 仓库根 VERSION, 与 cwd 无关; HTTP contract version 不动;
- MCP render 资源闸门在 RDKit to_thread 之前, 拒绝时零调用, 异常时释放租约, 两工具共用池;
- structure_exit 兼容契约仍存在;
- AI 接入叙事: /guide MCP-first, HTTP API 是兼容路径, Skill 是可选工作流, AI Key 共用。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# 本文件的用例不访问真实数据库/Redis: 只给 settings 一个满足必填校验的占位 DSN。
os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://governance:governance@127.0.0.1:5432/test_hgs",
)

import api.core.rate_limit as rate_limit  # noqa: E402
import api.mcp_server as mcp_server  # noqa: E402
import api.mol as mol  # noqa: E402
import api.services.rendering as render_service  # noqa: E402
import api.routes as routes  # noqa: E402
import api.skills as skills  # noqa: E402
from api.core.security import Actor  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

FAKE_SVG = "<svg/>"
ORDER: list = []


class _Rows:
    """最小 result stub: 覆盖 scalars()/first()/all()/scalar() 等常见取用方式。"""

    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)

    def first(self):
        return self._values[0] if self._values else None

    def fetchone(self):
        return self._values[0] if self._values else None

    def scalar(self):
        return self._values[0] if self._values else None


class _FakeSession:
    def __init__(self, log: list, rows):
        self._log = log
        self._rows = rows

    async def execute(self, stmt, params=None):
        self._log.append(" ".join(str(stmt).split()))
        return _Rows(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def fake_session_factory(log: list, rows=()):
    return lambda: _FakeSession(log, rows)


class FakeCtx:
    """MCP Context 桩: 只暴露 headers(认证上下文的唯一来源)。"""

    def __init__(self, headers: dict | None = None):
        self.headers = dict(headers or {})


AUTH_HEADERS = {"authorization": "Bearer test-actor"}


_ORIGINALS: dict = {}


def _save_originals() -> None:
    """首次 patch 前保存真实函数引用 —— tearDownModule 时还原。"""
    if _ORIGINALS:
        return
    _ORIGINALS.update(
        {
            "enforce": rate_limit.enforce,
            "acquire_lease": rate_limit.acquire_lease,
            "release_leases": rate_limit.release_leases,
            "actor_from_headers": mcp_server._actor_from_headers,
            "async_session": mcp_server.async_session,
            "smiles_to_svg": render_service.smiles_to_svg,
            "reaction_to_svg": render_service.reaction_to_svg,
        }
    )


def restore_runtime() -> None:
    """撤销模块级 monkeypatch: 本模块的 stub 不得污染同进程其他测试模块。"""
    if not _ORIGINALS:
        return
    rate_limit.enforce = _ORIGINALS["enforce"]
    rate_limit.acquire_lease = _ORIGINALS["acquire_lease"]
    rate_limit.release_leases = _ORIGINALS["release_leases"]
    mcp_server._actor_from_headers = _ORIGINALS["actor_from_headers"]
    mcp_server.async_session = _ORIGINALS["async_session"]
    render_service.smiles_to_svg = _ORIGINALS["smiles_to_svg"]
    render_service.reaction_to_svg = _ORIGINALS["reaction_to_svg"]
    _ORIGINALS.clear()


def tearDownModule() -> None:  # noqa: N802 (unittest 约定)
    restore_runtime()


def patch_runtime(row=None, deny=False, enforce_503=False, forbid_fake_sql=None, auth=False):
    """替换 rate_limit / mol / async_session, 记录调用顺序。

    auth=True 模拟带合法 Authorization 头的 MCP 请求(认证 actor 上下文);
    auth=False 模拟匿名上下文。两者都只替换测试桩, 不改产品代码。
    """
    _save_originals()
    ORDER.clear()

    async def fake_actor_from_headers(headers):
        ORDER.append(("actor", bool(headers)))
        return actor() if (auth and headers) else None

    async def fake_enforce(bucket, identity, limit, window):
        ORDER.append(("enforce", bucket, identity, limit))
        if enforce_503:
            from api.core.rate_limit import LimiterUnavailable
            raise LimiterUnavailable("rate limit backend unavailable")

    async def fake_acquire(bucket, identity, limit, ttl=None):
        ORDER.append(("acquire", bucket, identity, limit))
        return not deny

    async def fake_release_leases(held, bucket):
        ORDER.append(("release_leases", bucket, tuple(held)))

    rate_limit.enforce = fake_enforce
    rate_limit.acquire_lease = fake_acquire
    rate_limit.release_leases = fake_release_leases
    mcp_server._actor_from_headers = fake_actor_from_headers

    def track(name):
        def inner(*a, **k):
            ORDER.append(("rdkit", name))
            return FAKE_SVG
        return inner

    render_service.smiles_to_svg = track("smiles_to_svg")
    render_service.reaction_to_svg = track("reaction_to_svg")
    mcp_server.async_session = fake_session_factory([], row if row is not None else ())


def actor(auth_kind: str = "agent", scopes=("read",), actor_id: int = 7) -> Actor:
    return Actor(
        id=actor_id, username="t", display_name="t", email="t@example.com",
        role="user", avatar_path=None, auth_kind=auth_kind, token_id=None,
        scopes=tuple(scopes),
    )


def build_server():
    return mcp_server.build_mcp_server()


# ---------------------------------------------------------------------------
# B1 — slug 解析
# ---------------------------------------------------------------------------

class SkillSlugResolution(unittest.TestCase):
    def _resolve(self, who, rows):
        log: list = []
        with patch.object(mcp_server, "async_session", fake_session_factory(log, rows)):
            try:
                return asyncio.run(mcp_server._resolve_skill_slug("dup", who)), log
            except ToolError as exc:  # noqa: PERF203
                return exc, log

    def test_anonymous_candidates_are_public_only(self):
        result, log = self._resolve(None, [11])
        self.assertEqual(result, 11)
        sql = log[0]
        self.assertEqual(len(log), 1, "slug 解析必须只发一条查询")
        self.assertIn("visibility='public'", sql)
        self.assertNotIn("owner_id", sql, "匿名不得把 owner 维度纳入候选")
        self.assertNotIn("ORDER BY", sql.upper())
        self.assertNotIn("LIMIT", sql.upper())

    def test_authenticated_candidates_are_public_or_own(self):
        result, log = self._resolve(actor(actor_id=42), [11])
        self.assertEqual(result, 11)
        sql = log[0]
        self.assertIn("visibility='public' OR owner_id=:actor_id", sql)
        self.assertNotIn("ORDER BY", sql.upper())
        self.assertNotIn("LIMIT", sql.upper())

    def test_not_found_is_tool_error(self):
        result, _ = self._resolve(None, [])
        self.assertIsInstance(result, ToolError)
        self.assertIn("not found or not accessible", str(result))

    def test_single_match_returns_id(self):
        result, _ = self._resolve(None, [163])
        self.assertEqual(result, 163)

    def test_ambiguous_accessible_slug_fails_closed(self):
        result, _ = self._resolve(actor(), [11, 12])
        self.assertIsInstance(result, ToolError)
        self.assertIn("numeric skill_id", str(result))
        self.assertIn("Multiple accessible skills", str(result))

    def test_inaccessible_private_duplicate_does_not_leak(self):
        # 候选集里只有可访问的那一个 → 正常返回; 不可访问的 private 同名技能
        # 不在结果里, 错误信息也不出现任何 skill/slug 细节泄露。
        result, log = self._resolve(actor(actor_id=42), [11])
        self.assertEqual(result, 11)
        self.assertNotIn("private", log[0].lower())
        missing, _ = self._resolve(actor(actor_id=42), [])
        self.assertNotIn("owner_id=", str(missing))

    def test_numeric_skill_id_bypasses_resolver(self):
        def boom(*a, **k):
            raise AssertionError("numeric skill_id 不得进入 slug resolver")

        log: list = []
        with patch.object(mcp_server, "_resolve_skill_slug", boom), \
                patch.object(mcp_server, "async_session", fake_session_factory(log)):
            for value in (163, "163"):
                log.clear()
                try:
                    asyncio.run(build_server().call_tool(
                        "get_skill", {"skill_id": value}, context=FakeCtx()))
                except Exception:  # noqa: BLE001  数据 stub 下允许查询失败
                    pass
                self.assertFalse(
                    any("slug=:slug" in sql for sql in log),
                    f"numeric skill_id({value!r}) 不应发出 slug 解析查询",
                )

    def test_non_numeric_slug_enters_resolver(self):
        calls: list = []

        async def spy(candidate, who):
            calls.append(candidate)
            return 163

        log: list = []
        with patch.object(mcp_server, "_resolve_skill_slug", spy), \
                patch.object(mcp_server, "async_session", fake_session_factory(log)):
            try:
                asyncio.run(build_server().call_tool(
                    "get_skill", {"skill_id": "dup"}, context=FakeCtx()))
            except Exception:  # noqa: BLE001
                pass
        self.assertEqual(calls, ["dup"])


# ---------------------------------------------------------------------------
# B2/B6 — tool surface 与版本轴
# ---------------------------------------------------------------------------

class ToolSurfaceAndVersion(unittest.TestCase):
    def test_tool_set_is_exactly_fourteen(self):
        names = sorted(t.name for t in asyncio.run(build_server().list_tools()))
        self.assertEqual(len(names), 13, names)

    def test_version_comes_from_repo_root_version_file(self):
        expected = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(expected, r"^\d+\.\d+\.\d+$", "VERSION 必须是 X.Y.Z 事实")
        self.assertEqual(build_server().version, expected)
        self.assertEqual(mcp_server._release_version(), expected)

    def test_version_is_cwd_independent(self):
        expected = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO)
        for cwd in (str(REPO), tempfile.gettempdir(), "/"):
            done = subprocess.run(
                [sys.executable, "-c",
                 "import api.mcp_server as M; print(M._release_version())"],
                cwd=cwd, env=env, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            self.assertEqual(done.stdout.strip(), expected, f"cwd={cwd}")

    def test_http_contract_version_untouched(self):
        from api.core.config import settings
        self.assertEqual(settings.api_version, "1.0.0")

    def test_search_docs_state_has_more_authority(self):
        src = (REPO / "api" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn("has_more is authoritative for pagination", src)
        self.assertIn("total=None", src)
        agent_src = (REPO / "api" / "agent.py").read_text(encoding="utf-8")
        self.assertIn("has_more", agent_src)
        self.assertIn("total=None", agent_src)


# ---------------------------------------------------------------------------
# B4 — validate_skill 权限对齐
# ---------------------------------------------------------------------------

class ValidateSkillScope(unittest.TestCase):
    def test_rest_validate_skill_rejects_agent_token_without_scope(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(skills.validate_skill(file=object(), actor=actor(scopes=("read",))))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("skill:write", str(ctx.exception.detail))

    def test_rest_validate_skill_allows_agent_token_with_scope(self):
        # require_scope 通过后才会读到 file, 这里只验证权限闸门本身不拦。
        rate_limit_ok = True
        try:
            skills.require_scope(actor(scopes=("read", "skill:write")), "skill:write")
        except Exception:  # noqa: BLE001
            rate_limit_ok = False
        self.assertTrue(rate_limit_ok)

    def test_rest_validate_skill_calls_require_scope(self):
        src = (REPO / "api" / "skills.py").read_text(encoding="utf-8")
        head = src.split("async def validate_skill", 1)[1]
        body = head.split("async def ", 1)[0]
        self.assertIn('require_scope(actor, "skill:write")', body)

    def test_agent_guide_advertises_skill_write_for_skill_tools(self):
        """断言限定到 skill operations: 不得因 list_my_reactions 的合法 bearer 失败。"""
        src = (REPO / "api" / "agent.py").read_text(encoding="utf-8")
        for op_id in ('"id": "validate_skill"', '"id": "create_skill"'):
            self.assertIn(op_id, src)
            segment = src.split(op_id, 1)[1][:600]
            self.assertIn('"auth": "bearer:skill:write"', segment, op_id)
        # 裸 bearer 只允许出现在 list_my_reactions(仅需登录的读操作)。
        self.assertEqual(src.count('"auth": "bearer"'), 1)
        self.assertIn('"auth": "bearer",',
                      src.split('"id": "list_my_reactions"', 1)[1][:600])


# ---------------------------------------------------------------------------
# B5 — MCP render 资源闸门
# ---------------------------------------------------------------------------

class RenderResourceGate(unittest.TestCase):
    CASES = (
        ("render_molecule_svg", {"smiles": "CCO"}, None),
        ("render_reaction_svg", {"reaction_id": 1}, ("CCO>>CC=O",)),
    )

    def test_gate_runs_before_rdkit_and_releases_for_both_tools(self):
        for tool, args, row in self.CASES:
            with self.subTest(tool=tool):
                patch_runtime(row=row)
                out = asyncio.run(build_server().call_tool(tool, args, context=FakeCtx()))
                kinds = [step[0] for step in ORDER]
                self.assertIn(FAKE_SVG, str(out))
                gate = [i for i, k in enumerate(kinds) if k in ("enforce", "acquire")]
                rdkit = [i for i, k in enumerate(kinds) if k == "rdkit"]
                self.assertTrue(gate and rdkit)
                self.assertLess(max(gate), min(rdkit), "闸门必须在 RDKit to_thread 之前")
                self.assertEqual(kinds[-1], "release_leases", "租约必须 finally 释放")

    def test_both_tools_share_single_pool(self):
        """两工具共用同一资源池; 匿名限流为两层: 600/min 全局兜底 → 120/min 按IP。"""
        for tool, args, row in self.CASES:
            with self.subTest(tool=f"{tool}/anonymous"):
                patch_runtime(row=row)
                asyncio.run(build_server().call_tool(tool, args, context=FakeCtx()))
                buckets = {step[1] for step in ORDER
                           if step[0] in ("enforce", "acquire", "release_leases")}
                self.assertEqual(buckets, {mcp_server.MCP_RENDER_BUCKET})
                self.assertEqual(mcp_server.MCP_RENDER_BUCKET, "mcp-render")
                # 匿名: 600/min 全局兜底先执行, 120/min render gate 随后执行。
                self.assertEqual(
                    [(step[2], step[3]) for step in ORDER if step[0] == "enforce"],
                    [("anon-global", 600), ("anon:unknown", 120)],
                    "600 全局 gate 必须先于 120 render gate",
                )
                # 常量即外部契约: 不得为迁就旧断言把 600 改回 120。
                self.assertEqual(mcp_server.MCP_RENDER_ANON_GLOBAL_LIMIT, 600)
                self.assertEqual(mcp_server.MCP_RENDER_RATE_LIMIT, 120)
                kinds = [step[0] for step in ORDER]
                self.assertLess(max(i for i, k in enumerate(kinds) if k == "enforce"),
                                min(i for i, k in enumerate(kinds) if k == "acquire"),
                                "限频必须先于租约")
                self.assertEqual(kinds[-1], "release_leases", "租约必须 finally 释放")
            with self.subTest(tool=f"{tool}/anonymous+forwarded-for"):
                patch_runtime(row=row)
                asyncio.run(build_server().call_tool(
                    tool, args, context=FakeCtx({"x-forwarded-for": "203.0.113.9, 10.0.0.1"})))
                self.assertEqual(
                    [step[2] for step in ORDER if step[0] == "enforce"],
                    ["anon-global", "anon:203.0.113.9"],
                    "匿名按来源 IP 拆桶(取 x-forwarded-for 首段)",
                )
            with self.subTest(tool=f"{tool}/authenticated"):
                patch_runtime(row=row, auth=True)
                asyncio.run(build_server().call_tool(
                    tool, args, context=FakeCtx(AUTH_HEADERS)))
                self.assertEqual(
                    [(step[2], step[3]) for step in ORDER if step[0] == "enforce"],
                    [("actor:7", 120)],
                    "已认证身份不吃匿名全局兜底, 仍为 120 次/分钟",
                )

    def test_actor_inflight_and_global_inflight_bounds(self):
        """认证身份持 actor 租约(≤2)+ global 租约(≤4); 匿名只持 global 租约。"""
        for tool, args, row in self.CASES:
            with self.subTest(tool=f"{tool}/authenticated"):
                patch_runtime(row=row, auth=True)
                asyncio.run(build_server().call_tool(
                    tool, args, context=FakeCtx(AUTH_HEADERS)))
                limits = sorted(step[3] for step in ORDER if step[0] == "acquire")
                self.assertEqual(limits, [2, 4])
            with self.subTest(tool=f"{tool}/anonymous"):
                patch_runtime(row=row, auth=False)
                asyncio.run(build_server().call_tool(tool, args, context=FakeCtx()))
                acquires = [step for step in ORDER if step[0] == "acquire"]
                self.assertEqual([step[3] for step in acquires], [4])
                self.assertEqual([step[2] for step in acquires], ["global"])

    def test_actor_resolved_before_gate(self):
        """actor 必须在 MCP render gate 之前解析完成, 且不得晚于 RDKit。"""
        for tool, args, row in self.CASES:
            with self.subTest(tool=tool):
                patch_runtime(row=row, auth=True)
                asyncio.run(build_server().call_tool(
                    tool, args, context=FakeCtx(AUTH_HEADERS)))
                kinds = [step[0] for step in ORDER]
                self.assertIn("actor", kinds)
                self.assertLess(kinds.index("actor"), kinds.index("enforce"))
                if "rdkit" in kinds:
                    self.assertLess(kinds.index("actor"), kinds.index("rdkit"))

    def test_rate_reject_skips_rdkit(self):
        patch_runtime(deny=True)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(build_server().call_tool(
                "render_molecule_svg", {"smiles": "CCO"}, context=FakeCtx()))
        self.assertIn("concurrency limit", str(ctx.exception))
        self.assertFalse([step for step in ORDER if step[0] == "rdkit"])

    def test_redis_failure_fails_closed_without_rdkit(self):
        patch_runtime(enforce_503=True)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(build_server().call_tool(
                "render_molecule_svg", {"smiles": "CCO"}, context=FakeCtx()))
        self.assertIn("unavailable", str(ctx.exception))
        self.assertFalse([step for step in ORDER if step[0] == "rdkit"])

    def test_renderer_exception_still_releases_lease(self):
        patch_runtime()

        def boom(*a, **k):
            ORDER.append(("rdkit", "boom"))
            raise RuntimeError("rdkit exploded")

        render_service.smiles_to_svg = boom
        with self.assertRaises(Exception):
            asyncio.run(build_server().call_tool(
                "render_molecule_svg", {"smiles": "CCO"}, context=FakeCtx()))
        self.assertTrue([step for step in ORDER if step[0] == "release_leases"])

    def test_direct_smiles_guard_still_precedes_gate(self):
        patch_runtime()
        with self.assertRaises(Exception) as ctx:
            asyncio.run(build_server().call_tool(
                "render_molecule_svg", {"smiles": "C" * 600}, context=FakeCtx()))
        self.assertIn("512", str(ctx.exception))
        self.assertFalse([step for step in ORDER
                          if step[0] in ("enforce", "acquire", "rdkit")])


# ---------------------------------------------------------------------------
# B1 追补 — structure_exit 兼容契约
# ---------------------------------------------------------------------------

class StructureGateCompat(unittest.TestCase):
    def test_public_helpers_still_exist_and_import(self):
        for name in ("structure_enter", "structure_exit", "structure_slot", "release_leases"):
            self.assertTrue(callable(getattr(rate_limit, name, None)), name)

    def test_structure_exit_signature_unchanged(self):
        sig = inspect.signature(rate_limit.structure_exit)
        self.assertEqual(list(sig.parameters), ["held", "bucket"])
        self.assertEqual(sig.parameters["bucket"].default, "structure-search")

    def test_structure_enter_and_slot_use_structure_exit(self):
        src = (REPO / "api" / "core" / "rate_limit.py").read_text(encoding="utf-8")
        body = src.split("async def structure_enter", 1)[1]
        self.assertIn("structure_exit(held, bucket)", body)
        slot = src.split("def structure_slot", 1)[1] if "def structure_slot" in src else ""
        self.assertIn("structure_exit", slot)

    def test_routes_still_imports_the_same_names(self):
        # G2.3 final: HTTP/MCP 均经 shared orchestration(闸门 owner=
        # services/search.execute_search); routes 不再持有结构闸门符号
        from api.services import search as _search_service
        self.assertIn("execute_search", dir(routes))
        src = (REPO / "api" / "services" / "search.py").read_text(encoding="utf-8")
        self.assertIn("structure_exit", src)
        self.assertNotIn("release_leases", src, "search service 不应因 MCP batch 改写")


# ---------------------------------------------------------------------------
# C/D — AI 接入叙事(只锁结构语义)
# ---------------------------------------------------------------------------


class RepoWidePlaceholderHygiene(unittest.TestCase):
    """输出遮蔽误写入的占位符不得存在于仓库文本中。"""

    SUFFIXES = (".py", ".ts", ".tsx", ".md", ".txt", ".json", ".yaml", ".yml", ".css")
    SKIP = ("node_modules", ".next", "venv", ".git")

    def test_no_masked_placeholder_leaked_into_sources(self):
        # 检测串用 chr() 拼出, 使本测试文件自身也不含该字面量 —— 因此无需排除任何文件,
        # 生产源码扫描覆盖不降低。
        needle = chr(42) * 3
        bad: list = []
        for path in REPO.rglob("*"):
            if not path.is_file() or path.suffix not in self.SUFFIXES:
                continue
            if any(part in self.SKIP for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    bad.append(f"{path.relative_to(REPO)}:{lineno}")
        self.assertEqual(bad, [], f"占位符损坏: {bad}")

    def test_old_skill_url_is_gone_from_tracked_docs(self):
        bad: list = []
        for path in REPO.rglob("*"):
            if not path.is_file() or path.suffix not in (".md", ".tsx", ".ts", ".txt"):
                continue
            if any(part in self.SKIP for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "/skills/huagongshe-reaction-publisher/SKILL.md" in text:
                bad.append(str(path.relative_to(REPO)))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
