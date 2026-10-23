"""Notes contract tests that do not require a database."""

from __future__ import annotations

import ast
import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

# 限流映射测试会构造 api.core.config.settings — 用占位 URL, 不触库。
os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://notes:notes@127.0.0.1:5432/unused",
)

from api.schemas.notes import MAX_NOTE_REFERENCES, NoteBody
from api.services.identity import CHEMICAL_REFERENCE_TABLES

REPO = Path(__file__).resolve().parents[1]


class NoteSchemaTests(unittest.TestCase):
    def test_reference_ids_are_deduplicated_preserving_order(self):
        body = NoteBody(
            content="  observation  ",
            chemical_ids=[5, 5, 3],
            reaction_ids=[9, 9],
        )
        self.assertEqual(body.content, "observation")
        self.assertEqual(body.chemical_ids, [5, 3])
        self.assertEqual(body.reaction_ids, [9])

    def test_empty_or_over_limit_is_rejected(self):
        with self.assertRaises(ValidationError):
            NoteBody(content="   ")
        with self.assertRaises(ValidationError):
            NoteBody(
                content="x",
                chemical_ids=list(range(1, MAX_NOTE_REFERENCES + 2)),
            )

    def test_non_positive_reference_is_rejected(self):
        with self.assertRaises(ValidationError):
            NoteBody(content="x", chemical_ids=[0])

    def test_reference_ids_over_column_range_are_rejected(self):
        """引用 id 上界按引用列类型分开: 化合物 int4、反应 int8 ——
        越界在模型层 422, 不放进 SQL 撞库。"""
        # 化合物引用列是 int4: 超 int4 拒绝
        with self.assertRaises(ValidationError):
            NoteBody(content="x", chemical_ids=[2_147_483_648])
        # 反应引用列是 int8: int4 之上仍合法, int8 之上拒绝
        body = NoteBody(content="x", reaction_ids=[3_000_000_000])
        self.assertEqual(body.reaction_ids, [3_000_000_000])
        with self.assertRaises(ValidationError):
            NoteBody(content="x", reaction_ids=[9_223_372_036_854_775_808])
        # 两侧各自的上限值本身合法
        ok = NoteBody(content="x", chemical_ids=[2_147_483_647],
                      reaction_ids=[9_223_372_036_854_775_807])
        self.assertEqual(ok.chemical_ids, [2_147_483_647])
        self.assertEqual(ok.reaction_ids, [9_223_372_036_854_775_807])


class NoteArchitectureTests(unittest.TestCase):
    def test_service_is_transport_neutral(self):
        tree = ast.parse((REPO / "api/services/notes.py").read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertFalse(any(name.startswith("fastapi") for name in imports))
        self.assertFalse(any(name.startswith("mcp") for name in imports))

    def test_note_chemical_reference_is_identity_registered(self):
        rows = {
            (schema, table): cfg
            for schema, table, cfg in CHEMICAL_REFERENCE_TABLES
        }
        cfg = rows[("community", "note_chemicals")]
        self.assertEqual(cfg["strategy"], "DEDUPE_REKEY")
        self.assertEqual(tuple(cfg["dedupe_key"]), ("note_id",))
        self.assertEqual(tuple(cfg["merge_cols"]), ())

    def test_note_routes_require_session_for_mutations(self):
        src = (REPO / "api/notes.py").read_text(encoding="utf-8")
        for name in ("create_note", "update_note", "delete_note"):
            segment = src.split(f"async def {name}", 1)[1].split("\n\n@router.", 1)[0]
            self.assertIn("Depends(current_session)", segment, name)
        self.assertNotIn("require_scope", src, "v1.7.0 Notes Web CRUD must not create an agent scope")

    def test_reaction_note_field_is_not_repurposed(self):
        src = (REPO / "api/services/notes.py").read_text(encoding="utf-8")
        self.assertNotIn("chemistry.reactions SET note", src)
        self.assertNotIn("UPDATE chemistry.reactions", src)


class NoteRateLimitHttpMappingTests(unittest.TestCase):
    """服务层 neutral 限流异常 → HTTP 429/503(reactions 同口径)。"""

    def _actor(self):
        from api.core.security import Actor

        return Actor(id=1, username="u", display_name="u", email="e@x.local",
                     role="user", avatar_path=None, auth_kind="session")

    def _call(self, handler, exc):
        # services/notes.create|update 在函数体内 `from ..core.rate_limit
        # import enforce` — patch 模块属性即拦得住, db 不会被触碰。
        import api.core.rate_limit as rl

        async def boom(bucket, identity, limit, window_seconds):
            raise exc

        with patch.object(rl, "enforce", boom):
            return asyncio.run(handler(
                body=NoteBody(content="限流映射"),
                actor=self._actor(),
                db=None,
            ))

    def test_create_rate_limited_maps_429_with_headers(self):
        from api.core.rate_limit import RateLimited
        from api.notes import create_note
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(create_note, RateLimited("请求过于频繁，请稍后重试", retry_after=30))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "30")
        self.assertEqual(ctx.exception.headers["X-RateLimit-Remaining"], "0")

    def test_create_limiter_unavailable_maps_503(self):
        from api.core.rate_limit import LimiterUnavailable
        from api.notes import create_note
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(create_note, LimiterUnavailable("限速服务暂时不可用，请稍后重试"))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_update_rate_limited_maps_429(self):
        from api.core.rate_limit import RateLimited
        from api.notes import update_note
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(
                lambda **kw: update_note(note_id=1, **kw),
                RateLimited("请求过于频繁，请稍后重试", retry_after=5))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "5")


if __name__ == "__main__":
    unittest.main()
