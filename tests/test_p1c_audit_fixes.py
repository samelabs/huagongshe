"""R4/R5 audit-fix tests: sanitize-before-length-cap and hidden-note write
semantics (no-side-effect update/delete, owner list excludes hidden)."""

from __future__ import annotations

import re
import unittest
import uuid
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from api.schemas.notes import MAX_NOTE_CONTENT_LENGTH, NoteBody, sanitize_note_content

# ---------------------------------------------------------------------------
# R4: sanitize happens BEFORE the final length cap
# ---------------------------------------------------------------------------


class R4SanitizeBeforeLengthTests(unittest.TestCase):
    def test_raw_over_limit_accepted_when_sanitized_fits(self):
        # 30050 raw chars: 100 visible + 29950 Cf → sanitized = 100 ≤ 30000
        raw = "a" * 100 + "\u200d" * 29950
        self.assertEqual(len(raw), 30050)
        body = NoteBody(content=raw, visibility="private")
        self.assertEqual(len(body.content), 100)

    def test_rejected_when_still_over_limit_after_sanitize(self):
        # 30001 visible chars (no removable chars) → reject
        with self.assertRaises(ValidationError) as ctx:
            NoteBody(content="b" * (MAX_NOTE_CONTENT_LENGTH + 1), visibility="private")
        self.assertIn("30000", str(ctx.exception))

    def test_boundary_exactly_30000_after_sanitize(self):
        raw = "c" * (MAX_NOTE_CONTENT_LENGTH - 10) + "\u200c" * 10
        self.assertEqual(len(raw), MAX_NOTE_CONTENT_LENGTH)
        body = NoteBody(content=raw, visibility="private")
        self.assertEqual(len(body.content), MAX_NOTE_CONTENT_LENGTH - 10)

    def test_boundary_30001_after_sanitize_rejected(self):
        # raw 30011 (30001 visible + 10 Cf): sanitized = 30001 → still over → reject
        raw = "d" * 30001 + "\u200c" * 10
        self.assertEqual(len(raw), 30011)
        with self.assertRaises(ValidationError):
            NoteBody(content=raw, visibility="private")

    def test_create_and_update_share_the_same_model(self):
        # single NoteBody is the boundary for both POST /api/notes and
        # PUT /api/notes/{note_id} — verified structurally
        raw = "e" * 100 + "\ufeff" * 500
        parsed = NoteBody(content=raw, visibility="public")
        self.assertEqual(parsed.content, "e" * 100)
        again = NoteBody(content=parsed.content + "\u202e", visibility="public")
        self.assertEqual(again.content, "e" * 100)

    def test_no_field_max_length_precheck(self):
        # R4: Field(max_length=...) would run BEFORE the sanitizer and wrongly
        # reject raw>30000 whose sanitized form fits — it must be absent.
        source = open("api/schemas/notes.py", encoding="utf-8").read()
        self.assertIsNone(re.search(r"content:\s*str\s*=\s*Field\([^)]*max_length", source))


# ---------------------------------------------------------------------------
# DB part (gated)
# ---------------------------------------------------------------------------
_raw = None
try:
    from tests.db_gate import test_db_or_skip
    _raw = test_db_or_skip()
except Exception:
    _raw = None

ASYNC_URL = None
if _raw:
    _u = urlparse(_raw)
    if parse_qs(_u.query).get("test_sentinel") in (["hgs-test-db"], ["hgs-ephemeral-db"]):
        ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

if ASYNC_URL:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from api.services import notes as svc


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class R5HiddenNoteWriteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL, pool_size=5, max_overflow=0)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        self.user_ids: list[int] = []
        self.note_ids: list[int] = []
        async with self.Session() as db:
            self.owner = int((await db.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name,status)
                VALUES (:u,:e,'x','o','active') RETURNING id
            """), {"u": f"r5o_{self.tag}", "e": f"r5o_{self.tag}@example.test"})).scalar_one())
            self.user_ids.append(self.owner)
            await db.commit()

    async def asyncTearDown(self):
        async with self.Session() as db:
            if self.note_ids:
                await db.execute(text(
                    "DELETE FROM community.note_reactions WHERE note_id = ANY(:ids)"), {"ids": self.note_ids})
                await db.execute(text(
                    "DELETE FROM community.note_chemicals WHERE note_id = ANY(:ids)"), {"ids": self.note_ids})
                await db.execute(text(
                    "DELETE FROM community.notes WHERE id = ANY(:ids)"), {"ids": self.note_ids})
            if self.user_ids:
                await db.execute(text(
                    "DELETE FROM community.users WHERE id = ANY(:ids)"), {"ids": self.user_ids})
            await db.commit()
        await self.engine.dispose()

    async def _hidden_note(self, db) -> int:
        nid = int((await db.execute(text("""
            INSERT INTO community.notes(owner_user_id,visibility,moderation_status,content)
            VALUES (:o,'private','hidden','hidden note') RETURNING id
        """), {"o": self.owner})).scalar_one())
        await db.flush()
        self.note_ids.append(nid)
        return nid

    async def test_update_hidden_note_rejected_without_write(self):
        async with self.Session() as db:
            nid = await self._hidden_note(db)
            await db.commit()
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.update_note(
                    db, note_id=nid, actor_id=self.owner,
                    visibility="public", content="attempted unhide",
                    chemical_ids=[], reaction_ids=[])
            await db.rollback()
            # no side effect: content and moderation unchanged
            row = (await db.execute(text(
                "SELECT content, moderation_status FROM community.notes WHERE id=:i"),
                {"i": nid})).one()
            self.assertEqual(row[0], "hidden note")
            self.assertEqual(row[1], "hidden")

    async def test_delete_hidden_note_rejected_without_write(self):
        async with self.Session() as db:
            nid = await self._hidden_note(db)
            await db.commit()
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.delete_note(db, note_id=nid, actor_id=self.owner)
            await db.rollback()
            exists = (await db.execute(text(
                "SELECT count(*) FROM community.notes WHERE id=:i"), {"i": nid})).scalar_one()
            self.assertEqual(exists, 1)

    async def test_owner_list_excludes_hidden_notes(self):
        async with self.Session() as db:
            visible = int((await db.execute(text("""
                INSERT INTO community.notes(owner_user_id,visibility,moderation_status,content)
                VALUES (:o,'private','visible','ok note') RETURNING id
            """), {"o": self.owner})).scalar_one())
            self.note_ids.append(visible)
            await self._hidden_note(db)
            await db.commit()
            result = await svc.list_my_notes(
                db, actor_id=self.owner, visibility="all",
                chemical_id=None, reaction_id=None, page=1, page_size=20)
            self.assertEqual(result["total"], 1)
            self.assertEqual([item["id"] for item in result["items"]], [visible])

    async def test_update_visible_note_still_works(self):
        async with self.Session() as db:
            nid = int((await db.execute(text("""
                INSERT INTO community.notes(owner_user_id,visibility,moderation_status,content)
                VALUES (:o,'private','visible','before') RETURNING id
            """), {"o": self.owner})).scalar_one())
            await db.flush()
            self.note_ids.append(nid)
            await db.commit()
            updated = await svc.update_note(
                db, note_id=nid, actor_id=self.owner,
                visibility="private", content="after",
                chemical_ids=[], reaction_ids=[])
            self.assertEqual(updated["content"], "after")


if __name__ == "__main__":
    unittest.main()
