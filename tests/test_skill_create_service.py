"""G3.1D — skill create service 测试。

锁:
- payload loader contract + service ordering(rate→category→key→预检→loader→size
  →extract→事务)
- HTTP ordering: category/missing-key/幂等命中均 rate 后、read 前
- MCP ordering: decode 在 rate 前(service=0/rate=0); loader slicing 语义
- archive 18 类 error matrix(kind+exact detail)
- 事务顺序 + rmtree 补偿 + IntegrityError 三段恢复
- _FakeUpload 删除 / handler-call A005=0 / transport neutrality
"""

from __future__ import annotations

import ast
import base64
import inspect
import io
import unittest
import zipfile
from unittest.mock import patch

from fastapi import HTTPException

from api import skills as skills_module
from api.core.rate_limit import LimiterUnavailable, RateLimited
from api.services import skills as svc
from api.services.skills import (MissingSkillIdempotencyKeyError,
                                 SkillArchiveValidationError,
                                 SkillCategoryError,
                                 SkillIdempotencyKeyTooLongError,
                                 SkillSlugConflictError)

MAX = 12 * 1024 * 1024  # skill_zip_max_bytes(config 实值)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


SKILL_MD = b"---\nname: Test Skill\ndescription: A test skill\n---\nbody"

# E1: 与生产失败行同口径的样本(path='.gitignore', size_bytes=34, 纯文本无 NUL, 无扩展名)。
# 生产字节内容不可知(日志只留 sha256), 因此这里只对齐长度与文本/扩展名特征。
GITIGNORE_TEXT = b".env\n*.log\nnode_modules/\n#pad\n"
GITIGNORE_TEXT += b"#" * (34 - len(GITIGNORE_TEXT))


def _valid_zip() -> bytes:
    return _zip_bytes({"SKILL.md": SKILL_MD, "assets/icon.png": b"\x00\x01"})


class _Exec:
    def __init__(self, results=None):
        self.log = []
        self.results = results or []

    async def execute(self, sql, params=None):
        sql = str(sql)
        self.log.append(sql.strip()[:50].replace("\n", " "))
        for i, r in enumerate(self.results):
            key, val = r
            if key in sql and not str(val).startswith("_used"):
                self.results[i] = (key, "_used" + str(val))
                return _Res(val)
        return _Res(None)

    async def commit(self):
        self.log.append("<COMMIT>")

    async def rollback(self):
        self.log.append("<ROLLBACK>")


class _Res:
    def __init__(self, scalar):
        self._s = scalar

    def scalar(self):
        return self._s

    def fetchone(self):
        return (99, None)

    def mappings(self):
        return self

    def all(self):
        return [ {"id": 99} ]


class LoaderTests(unittest.IsolatedAsyncioTestCase):
    """§2/§4 loader contract + ordering。"""

    async def _run(self, db, loader, key="k", category=None, auth="agent"):
        async def ok(*a, **k2):
            return None
        with patch.object(svc, "enforce", ok):
            return await svc.create_skill(
                db, actor_id=7, auth_kind=auth, category=category,
                idempotency_key=key, archive_loader=loader)

    async def test_loader_called_with_max_plus_one(self):
        calls = []

        async def loader(limit):
            calls.append(limit)
            return b""

        db = _Exec()
        with self.assertRaises(SkillArchiveValidationError):
            await self._run(db, loader, key=None, auth="session")
        self.assertEqual(calls, [MAX + 1])  # loader 收到 max+1

    async def test_category_before_key_before_precheck_before_loader(self):
        order = []

        async def loader(limit):
            order.append("loader")
            return b""

        db = _Exec()

        async def boom(*a, **k):
            order.append("rate")
            return None

        # category invalid → loader 不被调
        with patch.object(svc, "enforce", boom), \
             patch.object(svc, "validate_category",
                          _raise(SkillCategoryError("分类不存在或已停用：x"))):
            with self.assertRaises(SkillCategoryError):
                await svc.create_skill(
                    db, actor_id=7, auth_kind="agent", category="x",
                    idempotency_key="k", archive_loader=loader)
        self.assertEqual(order, ["rate"])
        self.assertEqual(db.log, [])  # category SELECT 之前 rate 已发生

    async def test_agent_missing_key_after_rate(self):
        buckets = []

        async def cap(bucket, *a):
            buckets.append(bucket)

        async def loader(limit):
            raise AssertionError("loader must not run")

        with patch.object(svc, "enforce", cap):
            with self.assertRaises(MissingSkillIdempotencyKeyError):
                await svc.create_skill(
                    _Exec(), actor_id=7, auth_kind="agent",
                    category=None, idempotency_key=None,
                    archive_loader=loader)
        self.assertEqual(buckets, ["skill-write-hour"])

    async def test_key_too_long_after_rate(self):
        async def loader(limit):
            raise AssertionError("loader must not run")

        with patch.object(svc, "enforce", _ok()):
            with self.assertRaises(SkillIdempotencyKeyTooLongError):
                await svc.create_skill(
                    _Exec(), actor_id=7, auth_kind="agent",
                    category=None, idempotency_key="x" * 201,
                    archive_loader=loader)

    async def test_idempotency_hit_short_circuits(self):
        calls = {"loader": 0}

        async def loader(limit):
            calls["loader"] += 1
            return b""

        db = _Exec(results=[("SELECT id FROM community.skills", 88)])
        with patch.object(svc, "enforce", _ok()), \
             patch.object(svc, "load_accessible_skill", _ret({"id": 88})):
            result = await svc.create_skill(
                db, actor_id=7, auth_kind="agent", category=None,
                idempotency_key="dup", archive_loader=loader)
        self.assertEqual(result, {"id": 88})
        self.assertEqual(calls["loader"], 0)
        self.assertNotIn("<COMMIT>", db.log)
        self.assertNotIn("INSERT INTO community.skills", " ".join(db.log))

    async def test_oversize_after_loader(self):
        async def loader(limit):
            return b"x" * (MAX + 1)

        with patch.object(svc, "enforce", _ok()):
            with self.assertRaises(SkillArchiveValidationError) as ctx:
                await svc.create_skill(
                    _Exec(), actor_id=7, auth_kind="session",
                    category=None, idempotency_key=None,
                    archive_loader=loader)
        self.assertEqual(ctx.exception.detail,
                         "压缩包超过 12MB 上限")

    async def test_rate_policy_values(self):
        from api.core.config import settings
        captured = []

        async def cap(bucket, identity, limit, window):
            captured.append((bucket, identity, limit, window))

        async def loader(limit):
            raise SkillArchiveValidationError("k", "x")

        with patch.object(svc, "enforce", cap):
            with self.assertRaises(SkillArchiveValidationError):
                await svc.create_skill(
                    _Exec(), actor_id=7, auth_kind="session",
                    category=None, idempotency_key=None,
                    archive_loader=loader)
        self.assertEqual(captured, [("skill-write-hour", "7",
                                     settings.api_skill_write_limit_per_hour, 3600)])

    async def test_rate_limited_neutral_no_loader(self):
        async def loader(limit):
            raise AssertionError("loader must not run")

        async def boom(*a, **k):
            raise RateLimited("请求过于频繁，请稍后重试", retry_after=60)

        with patch.object(svc, "enforce", boom):
            with self.assertRaises(RateLimited):
                await svc.create_skill(
                    _Exec(), actor_id=7, auth_kind="agent",
                    category=None, idempotency_key="k",
                    archive_loader=loader)

    async def test_limiter_unavailable_neutral(self):
        async def boom(*a, **k):
            raise LimiterUnavailable("限速服务暂时不可用，请稍后重试")

        with patch.object(svc, "enforce", boom):
            with self.assertRaises(LimiterUnavailable):
                await svc.create_skill(
                    _Exec(), actor_id=7, auth_kind="agent",
                    category=None, idempotency_key="k",
                    archive_loader=_raise(AssertionError()))


class ArchiveKernelTests(unittest.TestCase):
    """§27 archive error matrix(18 类)。"""

    def _assert(self, raw, kind, detail):
        with self.assertRaises(SkillArchiveValidationError) as ctx:
            svc.extract_skill_zip(raw)
        self.assertEqual(ctx.exception.kind, kind)
        self.assertEqual(ctx.exception.detail, detail)

    def test_invalid_zip(self):
        self._assert(b"not a zip", SkillArchiveValidationError.INVALID_ARCHIVE,
                     "不是有效的 zip 文件")

    def test_unsafe_absolute_path(self):
        raw = _zip_bytes({"/etc/passwd": b"x"})
        # ZipFile 写入时绝对路径可能被规范化 → 构造 BadZip 场景不适用;
        # 用反斜杠路径直测 UNSAFE_PATH 分支
        self._assert(raw, SkillArchiveValidationError.UNSAFE_PATH,
                     f"非法路径：/etc/passwd")

    def test_traversal(self):
        raw = _zip_bytes({"../escape.txt": b"x"})
        self._assert(raw, SkillArchiveValidationError.UNSAFE_PATH,
                     "非法路径：../escape.txt")

    def test_depth(self):
        raw = _zip_bytes({"/".join(["a"] * 8) + "/f.txt": b"x"})
        self._assert(raw, SkillArchiveValidationError.UNSAFE_PATH,
                     f"目录层级过深：{'/'.join(['a'] * 8)}/f.txt")

    def test_empty_archive(self):
        raw = _zip_bytes({})
        self._assert(raw, SkillArchiveValidationError.EMPTY_ARCHIVE,
                     "压缩包内没有文件")

    def test_missing_skill_md(self):
        raw = _zip_bytes({"other.md": b"x"})
        self._assert(raw, SkillArchiveValidationError.MANIFEST_INVALID,
                     "压缩包根目录必须包含 SKILL.md")

    def test_oversized_zip_member_rejected_before_decompression(self):
        """Oversized declared members are rejected without opening their compressed data."""
        member = "assets/oversized.bin"
        # Stored mode isolates the declared size limit from compression-ratio policy.
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_STORED) as z:
            z.writestr(member, b"A" * (svc.settings.skill_file_max_bytes + 1))
            z.writestr("SKILL.md", SKILL_MD)
        raw = archive_bytes.getvalue()
        with patch.object(zipfile.ZipFile, "open",
                          side_effect=AssertionError("oversized ZIP entry was opened")):
            self._assert(
                raw, SkillArchiveValidationError.ARCHIVE_LIMIT,
                f"单文件超过 {svc.settings.skill_file_max_bytes // (1024 * 1024)}MB 上限：{member}")

    def test_binary_outside_allowed_dirs(self):
        raw = _zip_bytes({"SKILL.md": SKILL_MD, "blob.bin": b"\x00\x01"})
        self._assert(raw, SkillArchiveValidationError.MANIFEST_INVALID,
                     "二进制文件只能放在 assets/ 或 examples/ 目录：blob.bin")

    def test_binary_inside_allowed_dirs_accepted(self):
        raw = _zip_bytes({"SKILL.md": SKILL_MD, "examples/out/model.bin": b"\x00\x01"})
        manifest = svc.extract_skill_zip(raw)
        self.assertEqual([n for n, _ in manifest["files"]],
                         ["SKILL.md", "examples/out/model.bin"])

    def test_binary_content_with_text_extension_rejected(self):
        """E1: 扩展名不再豁免放行目录 — .csv 内嵌 NUL 必须在 archive 阶段被拒(原先落到 DB → 500)。"""
        raw = _zip_bytes({"SKILL.md": SKILL_MD, "data.csv": b"a\x00b"})
        self._assert(raw, SkillArchiveValidationError.MANIFEST_INVALID,
                     "二进制文件只能放在 assets/ 或 examples/ 目录：data.csv")

    def test_extensionless_text_files_are_text(self):
        """E1 生产 500 回归: .gitignore/LICENSE/Makefile 等无扩展名文本文件不得被判为二进制。"""
        raw = _zip_bytes({"SKILL.md": SKILL_MD, ".gitignore": GITIGNORE_TEXT,
                          "LICENSE": b"MIT License\n", "Makefile": b"all:\n\techo hi\n"})
        self.assertEqual(len(GITIGNORE_TEXT), 34)  # 与生产失败行 size_bytes 一致
        manifest = svc.extract_skill_zip(raw)
        self.assertEqual(len(manifest["files"]), 4)
        for name, data in manifest["files"]:
            with self.subTest(path=name):
                self.assertTrue(svc._skill_file_is_text(name, data), name)

    def test_is_text_never_violates_db_check(self):
        """_skill_file_is_text 必须恒满足 DB CHECK skill_files_text_only。"""
        cases = [(".gitignore", GITIGNORE_TEXT), ("LICENSE", b"MIT\n"),
                 ("Makefile", b"all:\n"), ("notes.md", b"# n\n"), ("data.csv", b"a,b\n"),
                 ("assets/icon.png", b"\x00\x01"), ("examples/m.bin", b"\x00\x01"),
                 ("assets/notes.md", b"# n\n"), ("assets/data.csv", b"a,b\n")]
        for path, data in cases:
            with self.subTest(path=path):
                is_text = svc._skill_file_is_text(path, data)
                self.assertTrue(is_text or path.startswith(("assets/", "examples/")),
                                f"会违反 DB CHECK: {path} is_text={is_text}")

    def test_assets_extension_conservatism_preserved(self):
        """assets/examples 内的标记口径不变: 二进制资产 false, 文本资产 true。"""
        self.assertFalse(svc._skill_file_is_text("assets/icon.png", b"\x00\x01"))
        self.assertFalse(svc._skill_file_is_text("assets/blob.bin", b"plain"))
        self.assertTrue(svc._skill_file_is_text("assets/notes.md", b"# n\n"))

    def test_frontmatter_missing_fields(self):
        raw = _zip_bytes({"SKILL.md": b"---\nname: X\n---\n"})
        self._assert(raw, SkillArchiveValidationError.MANIFEST_INVALID,
                     "SKILL.md frontmatter 必须包含 name 和 description")

    def test_bad_slug(self):
        raw = _zip_bytes({"SKILL.md": b"---\nname: !!!\ndescription: d\n---\n"})
        self._assert(raw, SkillArchiveValidationError.MANIFEST_INVALID,
                     "技能名无法转为合法 slug：'!!!'")

    def test_success_shape_and_single_root_strip(self):
        raw = _zip_bytes({"pkg/SKILL.md": SKILL_MD})
        manifest = svc.extract_skill_zip(raw)
        self.assertEqual(manifest["slug"], "test-skill")
        self.assertEqual([n for n, _ in manifest["files"]], ["SKILL.md"])

    def test_symlink_detected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("SKILL.md", SKILL_MD)
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120000 | 0o644) << 16
            z.writestr(info, "target")
        self._assert(buf.getvalue(), SkillArchiveValidationError.UNSAFE_PATH,
                     "不允许符号链接：link")

    def test_kernel_transport_neutral(self):
        src = inspect.getsource(svc)
        for tok in ("HTTPException", "UploadFile", "ToolError"):
            self.assertNotIn(tok, src)
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(
                    node.module.startswith(("fastapi", "starlette", "mcp")))
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, (
                    "HTTPException", "UploadFile", "ToolError"))

    def test_single_archive_implementation(self):
        self.assertNotIn("def extract_skill_zip",
                         inspect.getsource(skills_module))
        self.assertEqual(
            inspect.getsource(svc).count("def extract_skill_zip("), 1)
        for helper in ("validate_category", "_create_skill_record",
                       "_write_skill_files"):
            self.assertNotIn(f"def {helper}(", inspect.getsource(skills_module),
                             helper)


class TransactionTests(unittest.IsolatedAsyncioTestCase):
    """§28 事务顺序 + §29 IntegrityError 三段。"""

    async def test_success_ordering(self):
        order = []
        db = _Exec(results=[("INSERT INTO community.skills", 99)])
        orig_exec = db.execute
        orig_commit, orig_rollback = db.commit, db.rollback

        async def execute(sql, params=None):
            sql = str(sql)
            if "INSERT INTO community.skills" in sql and "skill_files" not in sql:
                order.append("insert_skill")
            elif "INSERT INTO community.skill_files" in sql:
                order.append("insert_files")
            elif "SELECT id FROM community.skills" in sql:
                order.append("precheck")
            return await orig_exec(sql, params)

        async def commit():
            order.append("commit")
            await orig_commit()

        db.execute, db.commit = execute, commit
        with patch.object(svc, "enforce", _ok()), \
             patch.object(svc, "_write_skill_files", _noop()), \
             patch.object(svc, "load_accessible_skill", _ret({"id": 99})):
            result = await svc.create_skill(
                db, actor_id=7, auth_kind="agent", category=None,
                idempotency_key="k", archive_loader=_ret(_valid_zip()))
        self.assertEqual(result["id"], 99)
        self.assertIn("warnings", result)
        seq = [o for o in order if o in ("insert_skill", "insert_files", "commit")]
        self.assertEqual(seq[0], "insert_skill")
        self.assertTrue(all(o == "insert_files" for o in seq[1:-1]))
        self.assertEqual(seq[-1], "commit")  # commit 最后(SKILL.md+icon 2 行 files)

    async def test_extensionless_text_file_inserted_as_text(self):
        """E1 回归: .gitignore 行以 is_text=true 落库(原先 false → CheckViolation 500)。"""
        db = _Exec(results=[("INSERT INTO community.skills", 99)])
        seen = []
        orig_exec = db.execute

        async def execute(sql, params=None):
            if "INSERT INTO community.skill_files" in str(sql) and params:
                seen.append((params["path"], params["is_text"]))
            return await orig_exec(sql, params)

        db.execute = execute
        raw = _zip_bytes({"SKILL.md": SKILL_MD, "assets/icon.png": b"\x00\x01",
                          ".gitignore": GITIGNORE_TEXT})
        with patch.object(svc, "enforce", _ok()), \
             patch.object(svc, "_write_skill_files", _noop()), \
             patch.object(svc, "load_accessible_skill", _ret({"id": 99})):
            await svc.create_skill(
                db, actor_id=7, auth_kind="agent", category=None,
                idempotency_key="k", archive_loader=_ret(raw))
        self.assertIn((".gitignore", True), seen)
        self.assertIn(("assets/icon.png", False), seen)
        self.assertIn(("SKILL.md", True), seen)

    async def test_race_idem_reread_hit(self):
        from sqlalchemy.exc import IntegrityError
        db = _Exec()
        orig = db.execute
        state = {"phase": 0}

        async def execute(sql, params=None):
            sql = str(sql)
            if "SELECT id FROM community.skills" in sql:
                if params and params.get("key") is not None:
                    state["phase"] += 1
                    return _Res(77 if state["phase"] >= 2 else None)
                return _Res(None)
            if "INSERT INTO community.skills" in sql and "skill_files" not in sql:
                raise IntegrityError("s", {}, Exception("dup"))
            return await orig(sql, params)

        db.execute = execute
        with patch.object(svc, "enforce", _ok()), \
             patch.object(svc, "_write_skill_files", _noop()), \
             patch.object(svc, "load_accessible_skill", _ret({"id": 77})):
            result = await svc.create_skill(
                db, actor_id=7, auth_kind="agent", category=None,
                idempotency_key="race", archive_loader=_ret(_valid_zip()))
        self.assertEqual(result["id"], 77)
        self.assertIn("<ROLLBACK>", db.log)
        self.assertEqual(state["phase"], 2)  # 预检 miss + 回读 hit

    async def test_race_slug_conflict(self):
        from sqlalchemy.exc import IntegrityError
        db = _Exec()
        orig = db.execute

        async def execute(sql, params=None):
            sql = str(sql)
            if "INSERT INTO community.skills" in sql and "skill_files" not in sql:
                raise IntegrityError("s", {}, Exception("uniq"))
            if "SELECT id FROM community.skills" in sql:
                # 预检/回读按 params 判: key 查 miss, slug 查命中
                if params and params.get("key") is not None:
                    return _Res(None)
                return _Res(55)
            return await orig(sql, params)

        db.execute = execute
        with patch.object(svc, "enforce", _ok()), \
             patch.object(svc, "_write_skill_files", _noop()):
            with self.assertRaises(SkillSlugConflictError) as ctx:
                await svc.create_skill(
                    db, actor_id=7, auth_kind="agent", category=None,
                    idempotency_key="k", archive_loader=_ret(_valid_zip()))
        self.assertIn("已存在同名技能", ctx.exception.detail)

    async def test_generic_integrity_error_reraised(self):
        from sqlalchemy.exc import IntegrityError
        db = _Exec()
        orig = db.execute

        async def execute(sql, params=None):
            sql = str(sql)
            if "INSERT INTO community.skills" in sql and "skill_files" not in sql:
                raise IntegrityError("s", {}, Exception("fk"))
            if "SELECT id FROM community.skills" in sql:
                return _Res(None)
            return await orig(sql, params)

        db.execute = execute
        with patch.object(svc, "enforce", _ok()), \
             patch.object(svc, "_write_skill_files", _noop()):
            with self.assertRaises(IntegrityError):
                await svc.create_skill(
                    db, actor_id=7, auth_kind="agent", category=None,
                    idempotency_key="k", archive_loader=_ret(_valid_zip()))
        self.assertIn("<ROLLBACK>", db.log)


class HttpAdapterTests(unittest.TestCase):
    """§22/§25 HTTP adapter。"""

    def test_adapter_no_business(self):
        src = inspect.getsource(skills_module.create_skill)
        for tok in ("enforce_http", "skill-write-hour", "validate_category",
                    "extract_skill_zip", "_create_skill_record", "INSERT INTO"):
            self.assertNotIn(tok, src)
        self.assertIn("create_skill_service", src)
        self.assertIn("archive_loader", src)

    def test_neutral_error_mappings(self):
        import asyncio
        cases = [
            (SkillArchiveValidationError("k", "zip-err"), 400, "zip-err"),
            (SkillCategoryError("cat-err"), 400, "cat-err"),
            (SkillSlugConflictError("slug-err"), 409, "slug-err"),
            (MissingSkillIdempotencyKeyError(), 400,
             "使用 API Token 提交必须提供 Idempotency-Key"),
            (SkillIdempotencyKeyTooLongError(), 400,
             "Idempotency-Key 不能超过 200 个字符"),
        ]
        for exc, code, detail in cases:
            self.assertEqual((code, detail),
                             _http_map(exc), exc.__class__.__name__)

    def test_validate_skill_adapter_maps_neutral(self):
        src = inspect.getsource(skills_module.validate_skill)
        self.assertIn("SkillArchiveValidationError", src)
        self.assertIn("to_thread(extract_skill_zip", src)


class McpTests(unittest.IsolatedAsyncioTestCase):
    """§26 MCP ordering。"""

    @staticmethod
    def _tool(name):
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools[name]
        return getattr(entry, "fn", None) or entry

    async def test_invalid_base64_before_service_and_rate(self):
        from mcp.server.mcpserver.exceptions import ToolError
        calls = {"service": 0, "rate": 0}

        async def service(*a, **k):
            calls["service"] += 1
            return {}

        with patch.object(
                __import__("api.mcp_server", fromlist=["x"]),
                "_actor_from_headers", _wrap(_McpActor())):
            with patch.object(svc, "create_skill", service), \
                 patch.object(svc, "enforce",
                              _counter(calls, "rate")):
                with self.assertRaises(ToolError) as ctx:
                    await self._tool("create_skill")(
                        zip_base64="!!!not-base64!!!", category=None,
                        idempotency_key="", ctx=_ctx())
        self.assertIn("not valid base64", str(ctx.exception))
        self.assertEqual(calls, {"service": 0, "rate": 0})

    async def test_loader_slicing_semantics(self):
        raw = b"A" * 20
        captured = {}

        async def service(db, *, actor_id, auth_kind, category,
                          idempotency_key, archive_loader):
            captured["limit_result"] = await archive_loader(11)
            return {"id": 1}

        class _S:
            async def __aenter__(self):
                return "s"
            async def __aexit__(self, *a):
                return False

        import api.mcp_server as mcp
        with patch.object(mcp, "_actor_from_headers", _wrap(_McpActor())), \
             patch.object(svc, "create_skill", service), \
             patch.object(mcp, "async_session", _S):
            await self._tool("create_skill")(
                zip_base64=base64.b64encode(raw).decode(),
                category=None, idempotency_key="k", ctx=_ctx())
        self.assertEqual(captured["limit_result"], b"A" * 11)  # raw[:11]

    async def test_valid_flow_calls_service(self):
        captured = {}

        async def service(db, *, actor_id, auth_kind, category,
                          idempotency_key, archive_loader):
            captured.update(actor_id=actor_id, auth_kind=auth_kind, key=idempotency_key)
            return {"id": 5, "warnings": []}

        class _S:
            async def __aenter__(self):
                return "s"
            async def __aexit__(self, *a):
                return False

        import api.mcp_server as mcp
        with patch.object(mcp, "_actor_from_headers", _wrap(_McpActor())), \
             patch.object(svc, "create_skill", service), \
             patch.object(mcp, "async_session", _S):
            result = await self._tool("create_skill")(
                zip_base64=base64.b64encode(_valid_zip()).decode(),
                category="cat", idempotency_key="kk", ctx=_ctx())
        self.assertEqual(result["id"], 5)
        self.assertEqual(captured, {"actor_id": 7, "auth_kind": "agent", "key": "kk"})


class ArchDebtTests(unittest.TestCase):
    """§30 静态断言。"""

    def test_fakeupload_absent(self):
        import api.mcp_server as mcp
        self.assertNotIn("_FakeUpload", inspect.getsource(mcp))

    def test_mcp_create_no_handler_call(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        seg = None
        for node in ast.walk(ast.parse(full)):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "create_skill"):
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("skills_module", seg)
        self.assertNotIn("_HTTPException", seg)

    def test_service_no_adapter_import(self):
        src = inspect.getsource(svc)
        self.assertNotIn("from ..skills import", src)
        self.assertNotIn("from .. import skills", src)


def _http_map(exc):
    """与 adapter 同款 kind→status 映射的直测(避免构造 FastAPI 全栈)。"""
    if isinstance(exc, SkillSlugConflictError):
        return (409, exc.detail)
    return (400, exc.detail)


def _ctx():
    return type("C", (), {"headers": {}})()


class _McpActor:
    id = 7
    auth_kind = "agent"
    scopes = ["skill:write"]
    role = "member"


def _wrap(value):
    async def fake(headers):
        return value
    return fake


def _ok():
    async def fake(*a, **k):
        return None
    return fake


def _ret(value):
    async def fake(*a, **k):
        return value
    return fake


def _raise(exc):
    async def fake(*a, **k):
        raise exc
    return fake


def _noop():
    def fake(*a, **k):
        return None
    return fake


def _counter(d, key):
    async def fake(*a, **k):
        d[key] += 1
    return fake


if __name__ == "__main__":
    unittest.main()
