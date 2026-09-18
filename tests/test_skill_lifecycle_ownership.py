"""E4 — Skill lifecycle consistency & ownership(delete/update/archive/file read)。

锁的是**真实状态转换**, 不是调用形状。每个用例精确断言三件事与调用方看到的
结果一致: DB 行状态 / canonical skill 目录 / tombstone 残留。

- §4 delete matrix: 5 个 DB+FS 组合态 + 3 类 fault 注入(stage rename 失败 /
  DB delete+commit 失败+restore 成功 / DB 失败+restore 失败 / commit 成功+
  final purge 失败)+ repeated delete 语义;
- RESTORE_FAILED / PURGE_FAILED 的残留状态必须**确定、可诊断、不会被下一步代码
  误认为正常完整状态**: 错误 detail 携带 tombstone 路径, canonical 路径不存在,
  DB 行状态与错误语义一致 —— 测试逐项断言, 不为过测试弱化断言;
- §10 archive/file 域 8 态(含 path traversal / symlink 既有保护不退化);
- §3 update: 真实实现只做 DB metadata mutation(无 FS 参与), 不虚构 FS fault;
- §5 create E1 补偿: 主异常不得被 cleanup 失败覆盖, 只能留结构化 warning。

全部 hermetic: skill_root → tempdir; DB 为最小事务模型 stub(状态机, 非 SQL 文本
匹配); FS 故障用真实 OS 权限语义(chmod 0o500/0o000 → EACCES), 非 mock。

注: 故障注入依赖真实 OS 权限语义, 因此要求**非 root** 测试环境(本机与 CI 均为
euid=1000)。若在 root 下运行, 这些用例会明确变红(而非静默 skip 或假绿)。
"""

from __future__ import annotations

import ast
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from api.core.config import settings
from api.services import skills as svc

SID = 42
OWNER = 7

FS_MUTATORS = ("rmtree", "rename", "replace", "copytree", "copyfile", "move",
               "unlink", "rmdir", "mkdir")


def _src_of(rel):
    return Path(rel).read_text(encoding="utf-8")


def _func_source(src, name):
    """AST 定位函数体源码 —— 避免同名注释/文档字符串造成文本匹配假绿。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"未找到函数 {name}")


def _fs_mutator_calls(rel):
    """返回源码中真实发生的 filesystem 变更调用名(AST 调用点, 非文本)。"""
    found = []
    for node in ast.walk(ast.parse(_src_of(rel))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in FS_MUTATORS:
            found.append(node.func.attr)
    return found


def _sql_texts(rel):
    """返回源码中真正传给 execute()/text() 的 SQL 字面量(AST 调用点)。

    只取调用实参, 因此注释与文档字符串里的 SQL 示例不会造成假红/假绿。
    """
    out = []
    for node in ast.walk(ast.parse(_src_of(rel))):
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname in ("execute", "text"):
                for arg in node.args:
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Constant) \
                                and isinstance(sub.value, str):
                            out.append(sub.value)
    return out


def _rmtree_calls(rel):
    """返回源码中 rmtree 调用点(用于断言不带 ignore_errors)。"""
    return [node for node in ast.walk(ast.parse(_src_of(rel)))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "rmtree"]


# ---------------------------------------------------------------------------
# DB stub — 最小事务模型
# ---------------------------------------------------------------------------


class _FetchOne:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def scalar(self):
        if self._row is None:
            return None
        return self._row[0] if isinstance(self._row, (list, tuple)) else self._row


class _FetchAll:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _access_row(title="T", description="D", owner_id=OWNER, visibility="private"):
    return [SID, owner_id, "slug", title, description, "MIT", "chem", "user",
            visibility, False, 2, 20, "2026-01-01", "2026-01-02", "u1", "U1"]


class _LifecycleDB:
    """delete/update 用事务模型 stub。

    pending 语义与真实事务一致: execute 只写 pending; commit 才落到 state;
    rollback 丢弃 pending。这样"DB 失败后行仍在"是模型保证, 不是断言假设。
    """

    def __init__(self, *, row_exists=True, files=None, fail_delete=False,
                 fail_commit=False, fail_update=False, title="T",
                 description="D"):
        self.state = {"exists": row_exists, "title": title,
                      "description": description}
        self.files = files if files is not None else [
            {"path": "SKILL.md", "is_text": True, "size_bytes": 6}]
        self.fail_delete = fail_delete
        self.fail_commit = fail_commit
        self.fail_update = fail_update
        self.pending = {}
        self.commit_calls = 0
        self.rollback_calls = 0
        self.statements: list[str] = []

    # -- SQL 分派(按语义特征, 不按逐字文本) -----------------------------
    async def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        self.statements.append(s)
        if "FOR UPDATE" in s:
            return _FetchOne(SID if self.state["exists"] else None)
        if s.startswith("DELETE FROM community.skills"):
            if self.fail_delete:
                raise RuntimeError("E4 injected delete failure")
            self.pending["delete"] = True
            return _FetchOne(None)
        if s.startswith("UPDATE community.skills SET"):
            if self.fail_update:
                raise RuntimeError("E4 injected update failure")
            if params.get("title") is not None:
                self.pending["title"] = params["title"]
            if params.get("description") is not None:
                self.pending["description"] = params["description"]
            return _FetchOne(None)
        if "FROM community.skills s JOIN community.users u" in s:
            if not self.state["exists"]:
                return _FetchOne(None)
            return _FetchOne(_access_row(title=self.state["title"],
                                         description=self.state["description"]))
        if "SELECT path FROM community.skill_files" in s:
            return _FetchAll([(f["path"],) for f in self.files])
        if "SELECT is_text,size_bytes FROM community.skill_files" in s:
            for f in self.files:
                if f["path"] == params.get("path"):
                    return _FetchOne((f["is_text"], f["size_bytes"]))
            return _FetchOne(None)
        raise AssertionError(f"unexpected SQL in stub: {s[:120]}")

    async def commit(self):
        self.commit_calls += 1
        if self.fail_commit:
            raise RuntimeError("E4 injected commit failure")
        if self.pending.pop("delete", False):
            self.state["exists"] = False
        for k in ("title", "description"):
            if k in self.pending:
                self.state[k] = self.pending.pop(k)

    async def rollback(self):
        self.rollback_calls += 1
        self.pending.clear()


class _CreateStubDB:
    """create 补偿用例用: slug 预检 → INSERT → files → commit → access readback。"""

    def __init__(self, *, fail_commit=False):
        self.fail_commit = fail_commit
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        if "WHERE owner_id=:owner AND slug=:slug" in s:
            return _FetchOne(None)
        if s.startswith("INSERT INTO community.skills"):
            return _FetchOne((SID, "2026-01-01"))
        if s.startswith("INSERT INTO community.skill_files"):
            return _FetchOne(None)
        if "FROM community.skills s JOIN community.users u" in s:
            return _FetchOne(_access_row())
        raise AssertionError(f"unexpected SQL in create stub: {s[:120]}")

    async def commit(self):
        self.commit_calls += 1
        if self.fail_commit:
            raise RuntimeError("E4 injected create commit failure")

    async def rollback(self):
        self.rollback_calls += 1


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------


class _LifecycleBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="e4-skill-root-"))
        self._orig_root = settings.skill_root
        settings.skill_root = str(self.root)
        self.canonical = self.root / str(SID)

    def tearDown(self):
        settings.skill_root = self._orig_root
        os.chmod(self.root, 0o755)
        for p in self.root.iterdir():
            if p.is_dir():
                os.chmod(p, 0o755)
        shutil.rmtree(self.root, ignore_errors=True)

    # -- FS helpers ------------------------------------------------------
    def _make_skill_dir(self, files=None):
        payload = {"SKILL.md": b"# t\n"} if files is None else files
        self.canonical.mkdir(parents=True, exist_ok=True)
        for rel, data in payload.items():
            p = self.canonical / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def _tombstones(self):
        return sorted(p.name for p in self.root.iterdir()
                      if p.name.startswith(f".deleted-{SID}-"))

    def _lock_root(self):
        """真实 OS 级故障源: 非 root 下 rename/rmdir 需要父目录写权限。"""
        os.chmod(self.root, 0o500)

    def _stage_with_locked_root(self):
        """stage 成功(真实 rename) → 立即锁 root: 后续 restore rename / purge
        rmtree 会以真实 EACCES 失败, 用于 RESTORE_FAILED / PURGE_FAILED 注入。"""
        real = svc._stage_skill_dir

        def hook(skill_id):
            tomb = real(skill_id)
            self._lock_root()
            return tomb
        return hook


# ---------------------------------------------------------------------------
# §4 delete matrix
# ---------------------------------------------------------------------------


class DeleteMatrixTests(_LifecycleBase):
    async def test_db_exists_fs_exists_success_leaves_no_db_no_canonical(self):
        self._make_skill_dir({"SKILL.md": b"# t\n", "notes.md": b"n\n"})
        db = _LifecycleDB(row_exists=True)
        await svc.delete_skill_lifecycle(db, SID)
        self.assertFalse(db.state["exists"], "DB 行必须已删除")
        self.assertFalse(self.canonical.exists(), "canonical 目录必须已消失")
        self.assertEqual(self._tombstones(), [], "不得留下 tombstone 残留")
        self.assertEqual(db.commit_calls, 1)

    async def test_db_exists_fs_missing_delete_succeeds(self):
        """冻结 contract: FS 已无内容(orphan-free) → delete 仍成功, 不做 FS 动作。"""
        db = _LifecycleDB(row_exists=True)
        await svc.delete_skill_lifecycle(db, SID)
        self.assertFalse(db.state["exists"])
        self.assertFalse(self.canonical.exists())
        self.assertEqual(self._tombstones(), [])
        self.assertEqual(db.rollback_calls, 0)

    async def test_db_missing_fs_exists_orphan_not_silently_purged(self):
        """DB 行不存在 + canonical 残留 → 404 且**不动 FS**。

        策略(明确而非沉默): 无 DB 行的 orphan 目录不由 delete 路径清理 ——
        清理 orphan 需要扫描/后台机制(§5 禁自建 job system), 擅自 rmtree 会把
        "无行但有目录"的未知状态变成不可诊断。断言: 无 DELETE 语句、无
        tombstone、canonical 原样保留。
        """
        self._make_skill_dir()
        db = _LifecycleDB(row_exists=False)
        with self.assertRaises(svc.SkillNotFoundError) as ctx:
            await svc.delete_skill_lifecycle(db, SID)
        self.assertEqual(str(ctx.exception), "技能不存在")
        self.assertTrue(self.canonical.exists(), "orphan 目录不得被静默清理")
        self.assertEqual(self._tombstones(), [])
        self.assertFalse(any(s.startswith("DELETE FROM community.skills")
                             for s in db.statements), "不得发出 DELETE")
        self.assertEqual(db.commit_calls, 0)

    async def test_stage_rename_failure_db_and_canonical_untouched(self):
        """真实 rename 失败(EACCES): DB 不变、canonical 不变、明确 filesystem error。"""
        self._make_skill_dir({"SKILL.md": b"# t\n"})
        db = _LifecycleDB(row_exists=True)
        self._lock_root()
        with self.assertRaises(svc.SkillFilesystemError) as ctx:
            await svc.delete_skill_lifecycle(db, SID)
        self.assertEqual(ctx.exception.kind, svc.SkillFilesystemError.STAGE_FAILED)
        self.assertTrue(db.state["exists"], "DB 行必须不变")
        self.assertTrue(self.canonical.exists(), "canonical 必须不变")
        self.assertEqual(self._tombstones(), [], "stage 失败不得留下 tombstone")
        self.assertFalse(any(s.startswith("DELETE FROM community.skills")
                             for s in db.statements), "stage 失败不得发 DELETE")
        self.assertEqual(db.commit_calls, 0)

    async def test_db_commit_failure_restore_success_canonical_recovered(self):
        """commit 失败 + restore 成功 → DB 仍在、canonical 恢复、tombstone 零残留。"""
        self._make_skill_dir({"SKILL.md": b"# t\n", "notes.md": b"n\n"})
        db = _LifecycleDB(row_exists=True, fail_commit=True)
        with self.assertRaises(RuntimeError) as ctx:
            await svc.delete_skill_lifecycle(db, SID)
        self.assertEqual(str(ctx.exception), "E4 injected commit failure",
                         "DB 失败必须原样冒泡, 不得被补偿改写")
        self.assertTrue(db.state["exists"], "DB 行必须仍在")
        self.assertTrue(self.canonical.exists(), "canonical 必须已恢复")
        self.assertEqual((self.canonical / "notes.md").read_bytes(), b"n\n")
        self.assertEqual(self._tombstones(), [], "restore 成功后不得留 tombstone")
        self.assertEqual(db.rollback_calls, 1)

    async def test_db_delete_statement_failure_restores_canonical(self):
        """DELETE 语句自身失败(非 commit) → 同一补偿路径, 无 FS 残留。"""
        self._make_skill_dir()
        db = _LifecycleDB(row_exists=True, fail_delete=True)
        with self.assertRaises(RuntimeError):
            await svc.delete_skill_lifecycle(db, SID)
        self.assertTrue(db.state["exists"])
        self.assertTrue(self.canonical.exists())
        self.assertEqual(self._tombstones(), [])
        self.assertEqual(db.commit_calls, 0)

    async def test_db_failure_and_restore_failure_restore_failed_state(self):
        """DB 失败 + restore 失败 → RESTORE_FAILED, 精确断言四项状态。

        可诊断性: 错误 detail 必须携带 tombstone 绝对路径与原始 DB 失败原文;
        残留物是**非 canonical** 路径且内容完整(人工可 mv 回), canonical 路径
        不存在 —— 下一步代码不会把它当成正常完整状态。
        """
        self._make_skill_dir({"SKILL.md": b"# t\n", "notes.md": b"n\n"})
        db = _LifecycleDB(row_exists=True, fail_commit=True)
        with patch.object(svc, "_stage_skill_dir",
                          self._stage_with_locked_root()):
            with self.assertRaises(svc.SkillFilesystemError) as ctx:
                await svc.delete_skill_lifecycle(db, SID)
        exc = ctx.exception
        self.assertEqual(exc.kind, svc.SkillFilesystemError.RESTORE_FAILED)
        # ① DB 是否仍在
        self.assertTrue(db.state["exists"], "DB 行必须仍在(回滚生效)")
        # ② canonical dir 是否缺失
        self.assertFalse(self.canonical.exists(), "canonical 必须缺失")
        # ③ tombstone 是否存在(且内容完整 → 可人工恢复)
        tombs = self._tombstones()
        self.assertEqual(len(tombs), 1, f"必须留下恰好一个 tombstone: {tombs}")
        tomb = self.root / tombs[0]
        self.assertEqual((tomb / "notes.md").read_bytes(), b"n\n")
        # ④ 返回错误不能冒充成功 + 可诊断
        self.assertIn(str(tomb), exc.detail)
        self.assertIn("回滚失败", exc.detail)
        self.assertIn("E4 injected commit failure", exc.detail,
                      "detail 必须带原始 DB 失败根因")
        self.assertEqual(db.rollback_calls, 1)

    async def test_commit_success_purge_failure_purge_failed_state(self):
        """commit 成功 + final purge 失败 → PURGE_FAILED, 精确断言四项状态。

        成功契约(DB 无行 AND canonical 无)此刻**已成立**, 但残留 tombstone
        清理失败必须显式上报, 不得静默 success; 残留路径非 canonical 且错误
        detail 携带其路径 → 确定可诊断。
        """
        self._make_skill_dir({"SKILL.md": b"# t\n"})
        db = _LifecycleDB(row_exists=True)
        with patch.object(svc, "_stage_skill_dir",
                          self._stage_with_locked_root()):
            with self.assertRaises(svc.SkillFilesystemError) as ctx:
                await svc.delete_skill_lifecycle(db, SID)
        exc = ctx.exception
        self.assertEqual(exc.kind, svc.SkillFilesystemError.PURGE_FAILED)
        # ① DB 已删除
        self.assertFalse(db.state["exists"], "DB 行必须已删除(commit 已成功)")
        self.assertEqual(db.commit_calls, 1)
        # ② canonical dir 已消失
        self.assertFalse(self.canonical.exists(), "canonical 必须已消失")
        # ③ tombstone 仍存在
        tombs = self._tombstones()
        self.assertEqual(len(tombs), 1, f"必须留下恰好一个 tombstone: {tombs}")
        tomb = self.root / tombs[0]
        self.assertTrue(tomb.is_dir())
        self.assertFalse(tomb.is_symlink())
        # ④ 返回错误不能冒充成功 + 可诊断
        self.assertIn(str(tomb), exc.detail)
        self.assertIn("清理失败", exc.detail)
        # 该 id 的后续 delete 语义仍确定: 行已不存在 → 404
        db2 = _LifecycleDB(row_exists=False)
        with self.assertRaises(svc.SkillNotFoundError):
            await svc.delete_skill_lifecycle(db2, SID)

    async def test_repeated_delete_contract_preserved(self):
        """repeated delete: 第二次 → SkillNotFoundError("技能不存在") → 404, 无 FS 动作。"""
        self._make_skill_dir()
        db = _LifecycleDB(row_exists=True)
        await svc.delete_skill_lifecycle(db, SID)
        self.assertFalse(db.state["exists"])
        with self.assertRaises(svc.SkillNotFoundError) as ctx:
            await svc.delete_skill_lifecycle(db, SID)
        self.assertEqual(str(ctx.exception), "技能不存在")
        self.assertEqual(self._tombstones(), [])
        self.assertEqual(db.commit_calls, 1, "第二次调用不得再 commit")

    async def test_success_contract_no_ignore_errors_swallow(self):
        """purge 真实失败必须被 owner 看见: rmtree 不得带 ignore_errors。

        用 AST 判定调用点(注释/文档字符串里出现该词不算), 避免文本匹配假绿。
        """
        tree = ast.parse(Path(svc.__file__).read_text(encoding="utf-8"))
        rmtree_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "rmtree"
        ]
        self.assertTrue(rmtree_calls, "service 必须自己拥有物理清除点")
        for call in rmtree_calls:
            kw = {k.arg for k in call.keywords}
            self.assertNotIn("ignore_errors", kw,
                             "权威 delete success path 不得 ignore_errors")
        # _purge_skill_dir 是唯一物理清除 owner, 且没有 try/except 吞掉 OSError
        purge = _func_source(Path(svc.__file__).read_text(encoding="utf-8"),
                            "_purge_skill_dir")
        self.assertNotIn("except", purge, "purge 失败必须冒泡给 owner")


# ---------------------------------------------------------------------------
# §3 update matrix
# ---------------------------------------------------------------------------


class UpdateMatrixTests(_LifecycleBase):
    async def test_normal_update_applies_and_reads_back(self):
        db = _LifecycleDB(title="old", description="oldd")
        out = await svc.update_skill_metadata(
            db, SID, title="new", description=None, actor_id=OWNER)
        self.assertEqual(out["title"], "new")
        self.assertEqual(out["description"], "oldd", "未提供的字段不得被清空")
        self.assertEqual(db.state["title"], "new")
        self.assertEqual(db.commit_calls, 1)
        self.assertTrue(any("coalesce" in s for s in db.statements),
                        "null 字段必须走 coalesce 保持原值")

    async def test_validation_failure_no_db_touch(self):
        db = _LifecycleDB()
        with self.assertRaises(svc.SkillUpdateValidationError) as ctx:
            await svc.update_skill_metadata(
                db, SID, title=None, description=None, actor_id=OWNER)
        self.assertEqual(str(ctx.exception), "没有可更新的字段")
        self.assertEqual(db.statements, [], "校验失败不得发任何 SQL")
        self.assertEqual(db.commit_calls, 0)

    async def test_execute_failure_rollback_no_half_update(self):
        db = _LifecycleDB(title="old", description="oldd", fail_update=True)
        with self.assertRaises(RuntimeError) as ctx:
            await svc.update_skill_metadata(
                db, SID, title="new", description="newd", actor_id=OWNER)
        self.assertEqual(str(ctx.exception), "E4 injected update failure",
                         "DB 异常必须原样冒泡")
        self.assertEqual(db.commit_calls, 0)
        self.assertEqual((db.state["title"], db.state["description"]),
                         ("old", "oldd"), "不得半更新")

    async def test_commit_failure_rollback_fields_unchanged(self):
        """commit 失败 → 异常原样冒泡, 且不得留下半更新。

        注: update 路径(与 E4 之前的 adapter 实现逐字一致)不自持显式 rollback ——
        回滚保证来自 `get_db` 的 `async with async_session()`(异常时 session
        close 隐式回滚)。这里断言可观测契约; 真实 DB 上的回滚证明见
        tests/test_skill_lifecycle_persistence_db.py。
        """
        db = _LifecycleDB(title="old", description="oldd", fail_commit=True)
        with self.assertRaises(RuntimeError) as ctx:
            await svc.update_skill_metadata(
                db, SID, title="new", description="newd", actor_id=OWNER)
        self.assertEqual(str(ctx.exception), "E4 injected commit failure",
                         "commit 异常必须原样冒泡")
        self.assertEqual(db.commit_calls, 1)
        self.assertEqual((db.state["title"], db.state["description"]),
                         ("old", "oldd"), "rollback 后字段必须无半更新")
        # 回读(第二次独立 load)仍是旧值
        row = await svc.load_accessible_skill(db, SID, actor_id=OWNER)
        self.assertEqual(row["title"], "old")

    async def test_update_has_no_filesystem_participation(self):
        """真实实现只做 DB metadata mutation → 不得虚构 FS staging。"""
        self._make_skill_dir({"SKILL.md": b"# t\n"})
        before = sorted(p.relative_to(self.canonical).as_posix()
                        for p in self.canonical.rglob("*"))
        sentinel = MagicMock(side_effect=AssertionError("update 不得触碰 FS lifecycle"))
        db = _LifecycleDB(title="old", description="oldd")
        with patch.object(svc, "_stage_skill_dir", sentinel), \
             patch.object(svc, "_purge_skill_dir", sentinel), \
             patch.object(svc, "_restore_skill_dir", sentinel):
            await svc.update_skill_metadata(
                db, SID, title="new", description=None, actor_id=OWNER)
        after = sorted(p.relative_to(self.canonical).as_posix()
                       for p in self.canonical.rglob("*"))
        self.assertEqual(before, after, "update 不得改动 filesystem")
        self.assertEqual(sentinel.call_count, 0)


# ---------------------------------------------------------------------------
# §10 archive / file matrix
# ---------------------------------------------------------------------------


class ArchiveFileMatrixTests(_LifecycleBase):
    def _zip_names(self, payload: bytes):
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            return sorted(z.namelist())

    def _zip_read(self, payload: bytes, name: str):
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            return z.read(name)

    async def test_normal_archive_contains_all_manifest_files(self):
        self._make_skill_dir({"SKILL.md": b"# t\n", "notes.md": b"n\n"})
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 4},
                                 {"path": "notes.md", "is_text": True,
                                  "size_bytes": 2}])
        payload = await svc.build_skill_archive(db, SID)
        self.assertEqual(self._zip_names(payload), ["SKILL.md", "notes.md"])
        self.assertEqual(self._zip_read(payload, "notes.md"), b"n\n")

    async def test_directory_missing_is_explicit_neutral_error(self):
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 4}])
        with self.assertRaises(svc.SkillArchiveUnavailableError) as ctx:
            await svc.build_skill_archive(db, SID)
        self.assertEqual(ctx.exception.kind,
                         svc.SkillArchiveUnavailableError.DIR_MISSING)
        self.assertIn(str(self.canonical), ctx.exception.detail)

    async def test_manifest_row_file_missing(self):
        self._make_skill_dir({"SKILL.md": b"# t\n"})
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 4},
                                 {"path": "gone.md", "is_text": True,
                                  "size_bytes": 2}])
        with self.assertRaises(svc.SkillArchiveUnavailableError) as ctx:
            await svc.build_skill_archive(db, SID)
        self.assertEqual(ctx.exception.kind,
                         svc.SkillArchiveUnavailableError.FILE_MISSING)
        self.assertIn("gone.md", ctx.exception.detail)

    async def test_unreadable_file_mid_build_is_unreadable_kind(self):
        """构建中途读失败: is_file() 通过但 open() 失败 → UNREADABLE(非 500 无 detail)。"""
        self._make_skill_dir({"SKILL.md": b"# t\n", "secret.md": b"s\n"})
        os.chmod(self.canonical / "secret.md", 0o000)
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 4},
                                 {"path": "secret.md", "is_text": True,
                                  "size_bytes": 2}])
        with self.assertRaises(svc.SkillArchiveUnavailableError) as ctx:
            await svc.build_skill_archive(db, SID)
        self.assertEqual(ctx.exception.kind,
                         svc.SkillArchiveUnavailableError.UNREADABLE)
        self.assertIn("secret.md", ctx.exception.detail)

    async def test_archive_empty_manifest_returns_empty_zip(self):
        """DB 行不存在的 archive 语义: 由 adapter access 桥 404 拦截; owner 侧
        空 manifest → 空 zip(与迁移前逐字一致, 未新增行为)。"""
        db = _LifecycleDB(files=[])
        payload = await svc.build_skill_archive(db, SID)
        self.assertEqual(self._zip_names(payload), [])

    async def test_read_file_manifest_row_returns_text(self):
        self._make_skill_dir({"SKILL.md": b"# hello\n"})
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 8}])
        out = await svc.read_skill_file(db, SID, file_path="SKILL.md")
        self.assertEqual(out, {"path": "SKILL.md", "size_bytes": 8,
                               "content": "# hello\n"})

    async def test_read_file_binary_row_404_original_detail(self):
        self._make_skill_dir({"assets/icon.png": b"\x89PNG"})
        db = _LifecycleDB(files=[{"path": "assets/icon.png", "is_text": False,
                                  "size_bytes": 4}])
        with self.assertRaises(svc.SkillFileNotFoundError) as ctx:
            await svc.read_skill_file(db, SID, file_path="assets/icon.png")
        self.assertEqual(ctx.exception.detail,
                         "二进制文件请通过 archive 端点获取 zip")

    async def test_read_file_manifest_row_but_fs_missing(self):
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 4}])
        with self.assertRaises(svc.SkillFileNotFoundError) as ctx:
            await svc.read_skill_file(db, SID, file_path="SKILL.md")
        self.assertEqual(ctx.exception.detail, "文件不存在")

    async def test_read_file_path_traversal_rejected_without_fs_access(self):
        """穿越串不匹配任何 manifest 行 → 404, 不触 FS(既有防护不退化)。"""
        self._make_skill_dir()
        outside = self.root / "outside.txt"
        outside.write_bytes(b"secret\n")
        db = _LifecycleDB(files=[{"path": "SKILL.md", "is_text": True,
                                  "size_bytes": 4}])
        for evil in ("../outside.txt", "../../etc/passwd", "/etc/passwd",
                     "..%2Foutside.txt", "SKILL.md/../../outside.txt"):
            with self.assertRaises(svc.SkillFileNotFoundError) as ctx:
                await svc.read_skill_file(db, SID, file_path=evil)
            self.assertEqual(ctx.exception.detail, "文件不存在")
        self.assertEqual(outside.read_bytes(), b"secret\n")

    def test_extractor_ingress_protections_not_degraded(self):
        """既有 ingress 防护(E1/G3 kernel, E4 未改): traversal + symlink 拒绝。"""
        trav = self._make_zip({"./../evil.txt": b"x\n"})
        with self.assertRaises(svc.SkillArchiveValidationError) as ctx:
            svc.extract_skill_zip(trav)
        self.assertEqual(ctx.exception.kind,
                         svc.SkillArchiveValidationError.UNSAFE_PATH)
        link = self._make_zip({"SKILL.md": b"---\nname: a\ndescription: b\n---\n"},
                              symlink="evil")
        with self.assertRaises(svc.SkillArchiveValidationError) as ctx2:
            svc.extract_skill_zip(link)
        self.assertEqual(ctx2.exception.kind,
                         svc.SkillArchiveValidationError.UNSAFE_PATH)
        self.assertIn("不允许符号链接", ctx2.exception.detail)

    def _make_zip(self, files: dict[str, bytes], symlink: str | None = None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
            if symlink is not None:
                info = zipfile.ZipInfo(symlink)
                info.external_attr = (0o120777 << 16)
                z.writestr(info, "/etc/passwd")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# §5 create E1 补偿 contract
# ---------------------------------------------------------------------------


class CreateCompensationTests(_LifecycleBase):
    def _manifest(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("SKILL.md", b"---\nname: e4 comp\ndescription: d\n---\n")
        return svc.extract_skill_zip(buf.getvalue())

    async def test_primary_exception_survives_cleanup_success(self):
        db = _CreateStubDB(fail_commit=True)
        with self.assertRaises(RuntimeError) as ctx:
            await svc._create_skill_record(db, OWNER, self._manifest(), None, None)
        self.assertEqual(str(ctx.exception), "E4 injected create commit failure")
        self.assertFalse((self.root / str(SID)).exists(), "清理成功 → FS 零残留")
        self.assertEqual(db.rollback_calls, 1)

    async def test_primary_exception_not_masked_by_cleanup_failure(self):
        """§5: cleanup 失败只能留结构化 warning, 不得覆盖 create 原始 root cause。"""
        db = _CreateStubDB(fail_commit=True)
        logger = MagicMock()
        boom = OSError("E4 injected cleanup failure")
        with patch.object(svc, "logger", logger), \
             patch.object(svc, "_remove_skill_dir", MagicMock(side_effect=boom)):
            with self.assertRaises(RuntimeError) as ctx:
                await svc._create_skill_record(
                    db, OWNER, self._manifest(), None, None)
        self.assertEqual(str(ctx.exception), "E4 injected create commit failure",
                         "caller 必须看到原始 create 异常, 不是 cleanup 异常")
        self.assertIsInstance(ctx.exception, RuntimeError)
        self.assertTrue(logger.warning.called, "cleanup 失败必须留下结构化日志")
        msg = logger.warning.call_args[0][0]
        self.assertIn("补偿清理失败", msg)
        self.assertEqual(logger.warning.call_args[0][1], SID)
        self.assertEqual(logger.warning.call_args[0][3], boom)
        self.assertEqual(db.rollback_calls, 1)


# ---------------------------------------------------------------------------
# §7 architecture self-audit(源码级事实)
# ---------------------------------------------------------------------------


class LifecycleOwnershipGateTests(unittest.TestCase):
    def _src(self, rel):
        return _src_of(rel)

    def test_user_and_admin_delete_share_single_owner(self):
        user = self._src("api/skills.py")
        admin = self._src("api/admin.py")
        self.assertEqual(user.count("delete_skill_lifecycle(db"), 1)
        self.assertEqual(admin.count("delete_skill_lifecycle(db"), 1)
        # admin 不再自持 skill 删除 SQL
        admin_sql = " ".join(_sql_texts("api/admin.py"))
        self.assertNotIn("DELETE FROM community.skills", admin_sql)
        # admin 的 skill 删除不得再有 rmtree / FS 变更调用点
        self.assertNotIn("rmtree", _fs_mutator_calls("api/admin.py"))

    def test_adapter_has_no_lifecycle_db_sql_or_fs_mutation(self):
        for rel in ("api/skills.py", "api/admin.py"):
            sql = " ".join(_sql_texts(rel))
            self.assertNotIn("DELETE FROM community.skills", sql,
                             f"{rel} 不应自持 skill 删除 SQL")
            self.assertNotIn("FROM community.skill_files", sql,
                             f"{rel} 不应自持 skill_files 读取 SQL")
            self.assertEqual(_fs_mutator_calls(rel), [],
                             f"{rel} 不应含任何 FS 变更调用点")

    def test_service_has_no_transport_objects(self):
        src = self._src("api/services/skills.py")
        for token in ("fastapi", "starlette", "HTTPException", "ToolError",
                      "UploadFile", "StreamingResponse"):
            self.assertNotIn(token, src)

    def test_no_schema_change_markers(self):
        src = self._src("api/services/skills.py")
        for token in ("ALTER TABLE", "deleted_at", "cleanup_pending",
                      "tombstone table", "outbox"):
            self.assertNotIn(token, src)

    def test_registry_notes_are_factual_e4_updates(self):
        reg = self._src("api/contracts/registry.py")
        self.assertIn("E4:", reg)
        self.assertIn("delete_skill_lifecycle", reg)
        self.assertIn("update_skill_metadata", reg)
        self.assertIn("read_skill_file", reg)
        self.assertIn("build_skill_archive", reg)

    def test_archive_file_domain_single_owner(self):
        user = self._src("api/skills.py")
        self.assertNotIn("zipfile", user)
        self.assertNotIn("BytesIO", user)
        svc_src = self._src("api/services/skills.py")
        self.assertEqual(svc_src.count("def build_skill_archive"), 1)
        self.assertEqual(svc_src.count("def read_skill_file"), 1)
        self.assertEqual(svc_src.count("def delete_skill_lifecycle"), 1)
        self.assertEqual(svc_src.count("def update_skill_metadata"), 1)

    def test_e1_create_contract_not_drifted(self):
        """E4 只允许改 create compensation observability。"""
        src = self._src("api/services/skills.py")
        self.assertIn("def create_skill", src)
        self.assertIn("def _create_skill_record", src)
        self.assertIn("SkillSlugConflictError", src)
        self.assertIn("await asyncio.to_thread(_remove_skill_dir, skill_fs_dir(skill_id))", src)
        self.assertIn("补偿清理失败", src)


if __name__ == "__main__":
    unittest.main()
