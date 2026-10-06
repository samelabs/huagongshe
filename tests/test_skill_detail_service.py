"""G2.6C — Skill access kernel + detail service 测试。

锁:
- access kernel invariant: missing/private-anon/private-non-owner/
  private-admin-non-owner → 同一 SkillNotAccessibleError("技能不存在")
  (anti-enumeration); public/private-owner → 16 字段 dict
- detail service: files 查询、SKILL.md present/missing/decode-replace、
  script_warning 条件、manifest shape
- 9 个 production call site 全迁移(HTTP bridge); write owner 403 保留
- MCP get_skill 直调 detail service; slug 逻辑留 adapter; A005 关闭
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import MagicMock, patch

from api.services import skills as skills_service
from api.services.skills import SkillNotAccessibleError


def _skill_row(rid=1, owner_id=7, visibility="public"):
    return [rid, owner_id, "slug", "T", "D", "MIT", "chem", "user",
            visibility, False, 3, 100, "2026-01-01", "2026-01-02",
            "u1", "U1"]


def _file_row(**over):
    base = {"path": "SKILL.md", "is_text": True, "size_bytes": 10,
            "sha256": "x", "is_entry": True}
    base.update(over)
    return base


class _FetchResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _MappingsRow(dict):
    pass


class _MappingsResult:
    def __init__(self, rows):
        self._rows = [_MappingsRow(r) for r in rows]

    def all(self):
        return self._rows


class _FakeDB:
    """按查询特征应答: skills 行(可配)/skill_files/其它。"""

    def __init__(self, skill_row="UNSET", files=None):
        self._skill_row = skill_row
        self._files = files if files is not None else []
        self.calls = []

    async def execute(self, sql, params=None):
        sql_s = str(sql)
        self.calls.append(sql_s)
        if "FROM community.skills s" in sql_s:
            row = None if self._skill_row == "UNSET" else self._skill_row
            return _FetchResult(row)
        if "FROM community.skill_files" in sql_s:
            res = _MappingsResult(self._files)
            res.mappings = lambda: res
            return res
        return _FetchResult(None)


class AccessKernelTests(unittest.IsolatedAsyncioTestCase):
    async def _load(self, skill_row, actor_id):
        return await skills_service.load_accessible_skill(
            _FakeDB(skill_row=skill_row), 1, actor_id=actor_id)

    async def test_missing_neutral_error_exact_detail(self):
        with self.assertRaises(SkillNotAccessibleError) as ctx:
            await self._load(None, None)
        self.assertEqual(str(ctx.exception), "技能不存在")

    async def test_public_anonymous_allowed(self):
        d = await self._load(_skill_row(visibility="public"), None)
        self.assertEqual(d["id"], 1)

    async def test_public_actor_allowed(self):
        d = await self._load(_skill_row(visibility="public"), 99)
        self.assertEqual(d["visibility"], "public")

    async def test_private_anonymous_neutral_error(self):
        with self.assertRaises(SkillNotAccessibleError) as ctx:
            await self._load(_skill_row(visibility="private"), None)
        self.assertEqual(str(ctx.exception), "技能不存在")

    async def test_private_non_owner_neutral_error(self):
        with self.assertRaises(SkillNotAccessibleError):
            await self._load(_skill_row(owner_id=7, visibility="private"), 99)

    async def test_private_admin_non_owner_same_error(self):
        # admin role 不参与判定 —— 传任何非 owner actor_id 结果相同
        with self.assertRaises(SkillNotAccessibleError) as ctx:
            await self._load(_skill_row(owner_id=7, visibility="private"), 1)
        self.assertEqual(str(ctx.exception), "技能不存在")

    async def test_private_owner_allowed(self):
        d = await self._load(_skill_row(owner_id=7, visibility="private"), 7)
        self.assertEqual(d["owner_id"], 7)

    async def test_missing_detail_equals_private_unreadable_detail(self):
        details = []
        for row, actor in ((None, None),
                           (_skill_row(visibility="private"), None),
                           (_skill_row(visibility="private"), 99)):
            try:
                await self._load(row, actor)
            except SkillNotAccessibleError as exc:
                details.append(str(exc))
        self.assertEqual(len(set(details)), 1)
        self.assertEqual(details[0], "技能不存在")

    async def test_16_field_shape_unchanged(self):
        d = await self._load(_skill_row(), None)
        self.assertEqual(
            list(d.keys()),
            ["id", "owner_id", "slug", "title", "description", "license",
             "category", "origin", "visibility", "has_scripts",
             "file_count", "size_bytes", "created_at", "updated_at",
             "owner"])
        self.assertEqual(d["owner"], {"username": "u1", "display_name": "U1"})
        self.assertIsInstance(d["size_bytes"], int)


class DetailServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_files_query_and_assembly(self):
        db = _FakeDB(skill_row=_skill_row(),
                     files=[_file_row(), _file_row(path="a.py", is_entry=False)])
        with patch.object(skills_service, "skill_fs_dir") as fs:
            fs.return_value = MagicMock()
            fs.return_value.__truediv__ = lambda self, rel: MagicMock(
                is_file=MagicMock(return_value=False))
            result = await skills_service.get_skill_detail(db, 1, actor_id=None)
        self.assertEqual(len(result["files"]), 2)
        self.assertIsNone(result["skill_md"])  # fs 无文件 → None
        self.assertNotIn("script_warning", result)  # has_scripts=False

    async def test_skill_md_present(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            entry = Path(td) / "SKILL.md"
            entry.write_text("# 技能", encoding="utf-8")
            db = _FakeDB(skill_row=_skill_row(), files=[_file_row()])
            with patch.object(skills_service, "skill_fs_dir",
                              lambda sid: Path(td)):
                result = await skills_service.get_skill_detail(db, 1,
                                                               actor_id=None)
        self.assertEqual(result["skill_md"], "# 技能")

    async def test_skill_md_missing_none(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            db = _FakeDB(skill_row=_skill_row(), files=[_file_row()])
            with patch.object(skills_service, "skill_fs_dir",
                              lambda sid: Path(td)):
                result = await skills_service.get_skill_detail(db, 1,
                                                               actor_id=None)
        self.assertIsNone(result["skill_md"])

    async def test_skill_md_decode_replacement(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            entry = Path(td) / "SKILL.md"
            entry.write_bytes(b"\xff\xfeabc")
            db = _FakeDB(skill_row=_skill_row(), files=[_file_row()])
            with patch.object(skills_service, "skill_fs_dir",
                              lambda sid: Path(td)):
                result = await skills_service.get_skill_detail(db, 1,
                                                               actor_id=None)
        self.assertIn("abc", result["skill_md"])  # 替换解码不抛错

    async def test_script_warning_condition(self):
        row = _skill_row()
        row[9] = True  # has_scripts
        db2 = _FakeDB(skill_row=row, files=[_file_row()])
        with patch.object(skills_service, "skill_fs_dir",
                          lambda sid: MagicMock()):
            result = await skills_service.get_skill_detail(db2, 1,
                                                           actor_id=None)
        self.assertIn("script_warning", result)

    async def test_private_owner_and_non_owner(self):
        with self.assertRaises(SkillNotAccessibleError):
            await skills_service.get_skill_detail(
                _FakeDB(skill_row=_skill_row(visibility="private")), 1,
                actor_id=99)
        row = _skill_row(visibility="private")
        with patch.object(skills_service, "skill_fs_dir",
                          lambda sid: MagicMock()):
            d = await skills_service.get_skill_detail(
                _FakeDB(skill_row=row), 1, actor_id=7)
        self.assertEqual(d["visibility"], "private")

    async def test_no_entry_file_skips_fs_read(self):
        db = _FakeDB(skill_row=_skill_row(),
                     files=[_file_row(path="a.txt", is_entry=False)])
        with patch.object(skills_service, "skill_fs_dir") as fs:
            result = await skills_service.get_skill_detail(db, 1,
                                                           actor_id=None)
            fs.assert_not_called()
        self.assertIsNone(result["skill_md"])


class HttpMigrationTests(unittest.TestCase):
    """§19: 9 个 production call site 全迁移 + 关键行为。"""

    def test_old_helper_absent_and_all_callers_migrated(self):
        from api import skills as api_skills
        source = inspect.getsource(api_skills)
        self.assertNotIn("skill_accessible", source)
        # E4 后: bridge 调用=4(get_file/archive/update 授权门/delete 授权门)。
        # 原 5 = update 的 readback 也走 bridge; E4 把 readback 收进
        # services.skills.update_skill_metadata(唯一 owner), adapter 只留授权门。
        # 原 create×2 + _create_skill_record 尾部共 3 处随 create service
        # 下沉, 在 services.skills 直调 neutral load_accessible_skill。
        calls = source.count("await _load_accessible_skill_http(db")
        self.assertEqual(calls, 4)
        from api.services import skills as svc_skills
        svc_src = inspect.getsource(svc_skills)
        self.assertGreaterEqual(
            svc_src.count("await load_accessible_skill(db"), 4)
        self.assertNotIn("async def skill_accessible", source)
        self.assertEqual(source.count("def _load_accessible_skill_http"), 1)

    def test_bridge_is_transport_mapping_only(self):
        from api import skills as api_skills
        src = inspect.getsource(api_skills._load_accessible_skill_http)
        self.assertIn("load_accessible_skill", src)
        self.assertIn("404", src)
        self.assertNotIn("SELECT", src)
        self.assertNotIn("visibility", src)

    def test_get_skill_adapter_no_business_logic(self):
        from api import skills as api_skills
        src = inspect.getsource(api_skills.get_skill)
        self.assertIn("get_skill_detail_service", src)
        for token in ("SELECT", "skill_files", "read_text",
                      "skill_fs_dir", "entry_text"):
            self.assertNotIn(token, src)

    def test_http_get_skill_inaccessible_404_exact(self):
        from fastapi import HTTPException
        from api import skills as api_skills
        import asyncio

        async def boom(db, sid, *, actor_id):
            raise SkillNotAccessibleError("技能不存在")

        async def run():
            with patch.object(api_skills, "get_skill_detail_service", boom):
                await api_skills.get_skill(5, actor=None, db=object())
        try:
            asyncio.run(run())
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 404)
            self.assertEqual(exc.detail, "技能不存在")

    def test_write_owner_403_preserved_after_access(self):
        from api import skills as api_skills
        upd = inspect.getsource(api_skills.update_skill)
        dl = inspect.getsource(api_skills.delete_skill)
        self.assertIn("只能编辑自己创建的技能", upd)
        self.assertIn("只能删除自己创建的技能", dl)
        self.assertIn("_load_accessible_skill_http(db", upd)
        self.assertIn("_load_accessible_skill_http(db", dl)

    def test_get_skill_file_and_archive_use_bridge(self):
        from api import skills as api_skills
        gf = inspect.getsource(api_skills.get_skill_file)
        ar = inspect.getsource(api_skills.download_skill_archive)
        self.assertIn("_load_accessible_skill_http(db", gf)
        self.assertIn("_load_accessible_skill_http(db", ar)
        # E4: file-level 404 detail 不再由 adapter 持有, 而是 neutral error 的 detail
        # 经 adapter 映射(唯一 owner = services.skills.read_skill_file);
        # 两条原文仍在同一处被表达, 未丢失。
        svc = inspect.getsource(skills_service)
        self.assertIn("文件不存在", svc)
        self.assertIn("二进制文件请通过 archive 端点获取 zip", svc)
        self.assertIn("SkillFileNotFoundError", gf)
        self.assertIn("HTTPException(404, exc.detail)", gf)
        self.assertNotIn('"文件不存在"', gf)
        self.assertIn("SkillArchiveUnavailableError", ar)
        self.assertIn("HTTPException(500, exc.detail)", ar)

    def test_fs_dir_migrated_not_duplicated(self):
        from api import skills as api_skills
        source = inspect.getsource(api_skills)
        self.assertNotIn("def _skill_fs_dir", source)
        self.assertNotIn("def skill_fs_dir", source)  # 不在 adapter 复制
        svc = inspect.getsource(skills_service)
        self.assertIn("def skill_fs_dir", svc)
        self.assertIn('Path(settings.skill_root) / str(skill_id)', svc)

    def test_service_transport_neutral(self):
        source = inspect.getsource(skills_service)
        for token in ("fastapi", "starlette", "HTTPException", "ToolError",
                      "UploadFile"):
            self.assertNotIn(token, source)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(node.module.startswith(("fastapi",
                                                         "starlette", "mcp")))

    def test_canonical_access_predicate_count_is_one(self):
        """access predicate(单行 WHERE s.id)只在 service 出现一次;
        adapter 零 access SQL(list 的集合 JOIN 不属 access predicate)。"""
        svc = inspect.getsource(skills_service)
        self.assertEqual(svc.count("WHERE s.id=:id"), 1)
        from api import skills as api_skills
        self.assertEqual(
            inspect.getsource(api_skills).count("WHERE s.id=:id"), 0)


class McpTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _tool_fn():
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools.get("get_skill")
        if entry is None:
            raise AssertionError("get_skill not found in registry")
        fn = getattr(entry, "fn", None) or entry
        if not callable(fn):
            raise AssertionError(f"tool entry not callable: {type(entry)}")
        return fn

    async def _call(self, *, actor="UNSET", detail=None, headers=None,
                    **kwargs):
        from mcp.server.mcpserver.exceptions import ToolError
        import api.mcp_server as mcp

        if actor == "UNSET":
            async def fake_actor(headers):
                return None
        else:
            async def fake_actor(headers):
                return actor

        async def fake_detail(db, sid, *, actor_id):
            if detail == "RAISE":
                raise SkillNotAccessibleError("技能不存在")
            return detail if detail is not None else {"id": sid}

        ctx_headers = headers if headers is not None else {}
        with patch.object(mcp, "_actor_from_headers", fake_actor), \
             patch.object(skills_service, "get_skill_detail", fake_detail):
            try:
                return await (await self._tool_fn())(
                    ctx=type("C", (), {"headers": ctx_headers})(), **kwargs)
            except ToolError as exc:
                return exc

    async def test_numeric_get_works_anonymous_public(self):
        captured = {}

        async def fake_detail(db, sid, *, actor_id):
            captured.update(sid=sid, actor_id=actor_id)
            return {"id": sid, "skill_md": "x"}

        import api.mcp_server as mcp
        with patch.object(mcp, "_actor_from_headers", _wrap(None)), \
             patch.object(skills_service, "get_skill_detail", fake_detail):
            r = await (await self._tool_fn())(skill_id=42, ctx=_Ctx())
        self.assertEqual(r["id"], 42)
        self.assertIsNone(captured["actor_id"])

    async def test_slug_get_works_via_adapter_resolver(self):
        import api.mcp_server as mcp
        captured = {}

        async def fake_resolve(candidate, actor):
            return 77

        async def fake_detail(db, sid, *, actor_id):
            captured.update(sid=sid)
            return {"id": sid}

        with patch.object(mcp, "_resolve_skill_slug", fake_resolve), \
             patch.object(skills_service, "get_skill_detail", fake_detail):
            r = await (await self._tool_fn())(skill_id="my-slug", ctx=_Ctx())
        self.assertEqual(r["id"], 77)
        self.assertEqual(captured["sid"], 77)

    async def test_private_non_owner_tool_error_exact(self):
        from mcp.server.mcpserver.exceptions import ToolError
        actor = MagicMock(); actor.id = 99
        r = await self._call(actor=actor, detail="RAISE", skill_id=5)
        self.assertIsInstance(r, ToolError)
        self.assertEqual(str(r), "Skill not found or not accessible.")

    async def test_missing_tool_error_exact(self):
        from mcp.server.mcpserver.exceptions import ToolError
        r = await self._call(actor=None, detail="RAISE", skill_id=5)
        self.assertIsInstance(r, ToolError)
        self.assertEqual(str(r), "Skill not found or not accessible.")

    async def test_admin_non_owner_private_same_tool_error(self):
        from mcp.server.mcpserver.exceptions import ToolError
        actor = MagicMock(); actor.id = 1; actor.role = "admin"
        r = await self._call(actor=actor, detail="RAISE", skill_id=5)
        self.assertIsInstance(r, ToolError)
        self.assertEqual(str(r), "Skill not found or not accessible.")

    async def test_actor_own_private_detail(self):
        captured = {}
        actor = MagicMock(); actor.id = 7

        async def fake_detail(db, sid, *, actor_id):
            captured.update(actor_id=actor_id)
            return {"id": sid, "visibility": "private"}

        import api.mcp_server as mcp
        with patch.object(mcp, "_actor_from_headers", _wrap(actor)), \
             patch.object(skills_service, "get_skill_detail", fake_detail):
            r = await (await self._tool_fn())(skill_id=9, ctx=_Ctx())
        self.assertEqual(r["visibility"], "private")
        self.assertEqual(captured["actor_id"], 7)

    def test_mcp_no_http_no_leakage(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        seg = None
        for node in ast.walk(ast.parse(full)):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "get_skill"):
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("skills_module", seg)
        self.assertNotIn("HTTPException", seg)
        self.assertNotIn("request=None", seg)
        self.assertIn("_detail_service", seg)


class _Ctx:
    headers = {}


def _wrap(value):
    async def fake(headers):
        return value
    return fake


if __name__ == "__main__":
    unittest.main()
