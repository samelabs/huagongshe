"""v1.7.0 最后一处 Notes 权限边界收口 — 定向回归验证。

仅针对 api/services/notes.py::_validate_references() 的权限判定:
1. 非所有者引用他人私有 HRID 与引用不存在的 HRID 必须返回相同机器码
   reaction_not_accessible(不可区分存在性), 无论笔记可见性。
2. 所有者引用自己的非公开 HRID 创建公开笔记 → public_requires_public
   (准确提示); 创建私有笔记 → 通过。
3. 校验失败抛出时机在任何写入(_replace_references)之前 → 无 Notes
   写入副作用。

用内存 AsyncMock 风格 stub 数据库会话驱动真实 _validate_references,
不连真实数据库。
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock

from api.services.notes import NoteReferenceError, _validate_references


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    """按 SQL 内容分派的 stub: chemicals 点查 / reactions 点查。

    记录执行次数与语句, 供"失败时无写入副作用"断言(校验失败时
    除两条 SELECT 外不得有任何其他语句执行)。
    """

    def __init__(self, chemicals: list[int], reactions: list[dict]):
        self.chemicals = chemicals
        self.reactions = reactions
        self.statements: list[str] = []

    async def execute(self, sql, params=None):
        text = str(sql)
        self.statements.append(text)
        if "FROM chemistry.chemicals" in text:
            ids = params["ids"]
            return _FakeResult([cid for cid in ids if cid in self.chemicals])
        if "FROM chemistry.reactions" in text:
            ids = params["ids"]
            by_id = {int(r["id"]): r for r in self.reactions}
            return _FakeResult([by_id[i] for i in ids if i in by_id])
        raise AssertionError(f"意外语句: {text}")


def _reaction(rid: int, owner: int, *, public: bool, visible: bool = True) -> dict:
    return {
        "id": rid,
        "created_by_user_id": owner,
        "visibility": "public" if public else "private",
        "moderation_status": "visible" if visible else "hidden",
    }


PRIVATE_OTHER = _reaction(101, owner=1, public=False)          # 他人私有
MISSING = None                                                # 不存在
PRIVATE_OWN = _reaction(102, owner=7, public=False)            # 自己的私有
PUBLIC_HIDDEN_OTHER = _reaction(103, owner=1, public=True, visible=False)  # 他人公开但被隐藏


def _run(db, **kw):
    return _validate_references(
        db, actor_id=kw.pop("actor_id", 7),
        visibility=kw.pop("visibility", "private"),
        chemical_ids=[], reaction_ids=kw.pop("reaction_ids"),
    )


class NonOwnerPrivateVsMissing(unittest.TestCase):
    def _assert_not_accessible(self, visibility: str, reactions, reaction_ids):
        db = _FakeDB([], reactions)
        with self.assertRaises(NoteReferenceError) as ctx:
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                _run(db, actor_id=7, visibility=visibility, reaction_ids=reaction_ids))
        self.assertEqual(ctx.exception.kind, "reaction_not_accessible")

    def test_private_note_other_private_same_as_missing(self):
        self._assert_not_accessible("private", [PRIVATE_OTHER], [101])
        self._assert_not_accessible("private", [], [999])  # 不存在的 HRID

    def test_public_note_other_private_same_as_missing(self):
        # 关键边界: 公开笔记 + 他人私有 → 不再泄露为 public_requires_public
        self._assert_not_accessible("public", [PRIVATE_OTHER], [101])
        self._assert_not_accessible("public", [], [999])

    def test_private_note_other_hidden_public_same_as_missing(self):
        # 公开但被 moderation 隐藏的他人反应, 同样不可区分
        self._assert_not_accessible("private", [PUBLIC_HIDDEN_OTHER], [103])


class OwnerAccurateHint(unittest.TestCase):
    def test_owner_own_private_into_public_note(self):
        db = _FakeDB([], [PRIVATE_OWN])
        with self.assertRaises(NoteReferenceError) as ctx:
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                _run(db, actor_id=7, visibility="public", reaction_ids=[102]))
        self.assertEqual(ctx.exception.kind, "public_requires_public")

    def test_owner_own_private_into_private_note_passes(self):
        db = _FakeDB([], [PRIVATE_OWN])
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            _run(db, actor_id=7, visibility="private", reaction_ids=[102]))  # 不抛即通过


class NoWriteSideEffects(unittest.TestCase):
    def test_failure_executes_only_selects(self):
        db = _FakeDB([], [PRIVATE_OTHER])
        with self.assertRaises(NoteReferenceError):
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                _run(db, actor_id=7, visibility="public", reaction_ids=[101]))
        for stmt in db.statements:
            self.assertIn("SELECT", stmt.upper())
            self.assertNotIn("INSERT", stmt.upper())
            self.assertNotIn("DELETE", stmt.upper())
            self.assertNotIn("UPDATE", stmt.upper())
        # 且未出现 note 写入表
        joined = "\n".join(db.statements)
        self.assertNotIn("community.note_", joined)


if __name__ == "__main__":
    unittest.main()
