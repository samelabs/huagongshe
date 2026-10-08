"""Phase 1c tests: P-5 sanitization, P-1 access matrix, P-2 public profile API,
P-6/P-8 private+entity filter isolation.

Service/schema-level integration tests run against the gated TEST database
when available; the rest are pure-unit and always run.
"""

from __future__ import annotations

import re
import unittest
import uuid
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from api.schemas.notes import NoteBody, sanitize_note_content

CJK_SMILES = "乙醇 CCO\tscale-up 观察"
HANGUL = "한국어 노트 내용"
KANA = "日本語のノート"
EMOJI = "reaction done ✅🧪"
ZWJ_EMOJI = "family 👨‍👩‍👧‍👦"


class P5SanitizerUnitTests(unittest.TestCase):
    def test_crlf_and_cr_normalize_to_lf(self):
        self.assertEqual(sanitize_note_content("a\r\nb\rc\nd"), "a\nb\nc\nd")

    def test_preserves_lf_and_tab(self):
        self.assertEqual(sanitize_note_content("a\nb\tc"), "a\nb\tc")

    def test_strips_other_cc(self):
        # NUL, BEL, vertical tab, form feed, ESC, backspace are Cc but not \n/\t
        raw = "a\x00b\x07c\x0bd\x0ce\x1bf\x08g"
        self.assertEqual(sanitize_note_content(raw), "abcdefg")

    def test_strips_all_cf(self):
        # U+200D ZWJ, U+200C ZWNJ, U+FEFF BOM, U+202E RTL override are Cf
        raw = "a\u200db\u200cc\ufeffd\u202ee"
        self.assertEqual(sanitize_note_content(raw), "abcde")

    def test_cjk_smiles_emoji_unchanged(self):
        for value in (CJK_SMILES, HANGUL, KANA, EMOJI):
            self.assertEqual(sanitize_note_content(value), value)

    def test_zwj_sequences_not_preserved(self):
        # Documented consequence: U+200D is Cf and is removed.
        self.assertNotIn("\u200d", sanitize_note_content(ZWJ_EMOJI))

    def test_uses_unicodedata_not_enumeration(self):
        source = open("api/schemas/notes.py", encoding="utf-8").read()
        self.assertIn("unicodedata.category", source)
        # no per-codepoint enumeration like "\x00\x01\x02..."
        self.assertIsNone(re.search(r'"\\x[0-9a-f]{2}(\\x[0-9a-f]{2}){3,}"', source))

    def test_empty_after_sanitize_rejected_same_as_empty(self):
        with self.assertRaises(ValidationError):
            NoteBody(content="\u200d\u200c\r\n\t \x00", visibility="private")
        with self.assertRaises(ValidationError):
            NoteBody(content="   ", visibility="private")

    def test_length_limit_after_sanitize(self):
        # R4: length is enforced AFTER sanitization. Raw >30000 whose
        # sanitized form fits is ACCEPTED; still >30000 after sanitize rejects.
        body = NoteBody(content="a" * 29_990 + "\u200d" * 10, visibility="private")
        self.assertEqual(len(body.content), 29_990)
        with self.assertRaises(ValidationError):
            NoteBody(content="b" * 30_001, visibility="private")

    def test_create_and_update_share_rule(self):
        # Both create and update validate through the same NoteBody model.
        self.assertEqual(NoteBody(content="x\r\ny\u200d").content, "x\ny")


# ---------------------------------------------------------------------------
# DB integration part (gated by tests/db_gate.py)
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
class P1AccessMatrixDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL, pool_size=5, max_overflow=0)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        self.user_ids: list[int] = []
        self.note_ids: list[int] = []
        self.reaction_ids: list[int] = []
        async with self.Session() as db:
            self.owner = await self._user(db, "p1o")
            self.other = await self._user(db, "p1x")
            self.inactive = await self._user(db, "p1i", status="disabled")
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
            if self.reaction_ids:
                await db.execute(text(
                    "DELETE FROM chemistry.reactions WHERE id = ANY(:ids)"), {"ids": self.reaction_ids})
            if self.user_ids:
                await db.execute(text(
                    "DELETE FROM community.users WHERE id = ANY(:ids)"), {"ids": self.user_ids})
            await db.commit()
        await self.engine.dispose()

    async def _user(self, db, suffix, status="active") -> int:
        uid = int((await db.execute(text("""
            INSERT INTO community.users(username,email,password_hash,display_name,status)
            VALUES (:u,:e,'x',:d,:s) RETURNING id
        """), {
            "u": f"{suffix}_{self.tag}", "e": f"{suffix}_{self.tag}@example.test",
            "d": suffix, "s": status,
        })).scalar_one())
        self.user_ids.append(uid)
        return uid

    async def _note(self, db, owner, visibility, moderation="visible") -> int:
        nid = int((await db.execute(text("""
            INSERT INTO community.notes(owner_user_id,visibility,moderation_status,content)
            VALUES (:o,:v,:m,'matrix note') RETURNING id
        """), {"o": owner, "v": visibility, "m": moderation})).scalar_one())
        await db.flush()
        self.note_ids.append(nid)
        return nid

    async def _reaction(self, db, visibility="private") -> int:
        rid = int((await db.execute(text("""
            INSERT INTO chemistry.reactions(created_by_user_id,visibility,moderation_status,created_via,source_type)
            VALUES (:o,:v,'visible','web','self') RETURNING id
        """), {"o": self.owner, "v": visibility})).scalar_one())
        await db.flush()
        self.reaction_ids.append(rid)
        return rid

    async def test_full_access_matrix(self):
        async with self.Session() as db:
            pub = await self._note(db, self.owner, "public")
            priv = await self._note(db, self.owner, "private")
            hidden_pub = await self._note(db, self.owner, "public", moderation="hidden")
            hidden_priv = await self._note(db, self.owner, "private", moderation="hidden")
            inactive_pub = await self._note(db, self.inactive, "public")
            await db.commit()

            # anonymous public 200
            self.assertEqual((await svc.get_note(db, note_id=pub, actor_id=None))["id"], pub)
            # anonymous private 404
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.get_note(db, note_id=priv, actor_id=None)
            # owner private 200
            self.assertEqual((await svc.get_note(db, note_id=priv, actor_id=self.owner))["id"], priv)
            # non-owner private 404
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.get_note(db, note_id=priv, actor_id=self.other)
            # hidden 404 even for owner (both visibilities)
            for nid in (hidden_pub, hidden_priv):
                with self.assertRaises(svc.NoteNotAccessibleError):
                    await svc.get_note(db, note_id=nid, actor_id=self.owner)
            # inactive owner 404 even for the owner themselves
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.get_note(db, note_id=inactive_pub, actor_id=self.inactive)

    async def test_p2_public_user_notes_isolation_and_pagination(self):
        async with self.Session() as db:
            pub = await self._note(db, self.owner, "public")
            await self._note(db, self.owner, "private")
            await self._note(db, self.owner, "public", moderation="hidden")
            await self._note(db, self.inactive, "public")
            await db.commit()

            page = await svc.list_public_user_notes(db, user_id=self.owner, page=1, page_size=8)
            self.assertEqual(page["total"], 1)
            self.assertEqual([item["id"] for item in page["items"]], [pub])
            # pagination shape mirrors the list contract
            self.assertEqual(set(page), {"items", "total", "page", "page_size"})
            self.assertEqual(page["page"], 1)
            self.assertEqual(page["page_size"], 8)

    async def test_p2_public_notes_do_not_leak_private_hrid(self):
        async with self.Session() as db:
            rid = await self._reaction(db, visibility="public")
            note = await svc.create_note(
                db, actor_id=self.owner, visibility="public",
                content="will lose its reference", chemical_ids=[], reaction_ids=[rid])
            await db.execute(text(
                "UPDATE chemistry.reactions SET visibility='private' WHERE id=:r"), {"r": rid})
            await db.commit()
            page = await svc.list_public_user_notes(db, user_id=self.owner, page=1, page_size=8)
            for item in page["items"]:
                self.assertEqual(item["reaction_ids"], [])

    async def test_p5_stored_content_matches_sanitized_input(self):
        async with self.Session() as db:
            # End-to-end shape: raw input goes through NoteBody (the
            # server-authoritative sanitize boundary) before the service.
            body = NoteBody(
                content="line1\r\nline2\u200dline3\x00tail\ttab",
                visibility="private", chemical_ids=[], reaction_ids=[])
            note = await svc.create_note(
                db, actor_id=self.owner, visibility=body.visibility,
                content=body.content,
                chemical_ids=body.chemical_ids, reaction_ids=body.reaction_ids)
            await db.commit()
            row = (await db.execute(text(
                "SELECT content FROM community.notes WHERE id=:i"), {"i": note["id"]})).scalar_one()
            self.assertEqual(row, "line1\nline2line3tail\ttab")
            # API-shaped read returns exactly the stored content
            reread = await svc.get_note(db, note_id=note["id"], actor_id=self.owner)
            self.assertEqual(reread["content"], row)

    async def test_p6_private_filter_returns_only_own_private_for_entity(self):
        # /users/me/notes?visibility=private&reaction_id=X semantics via service.
        # Reaction is public+visible so both users may reference it; the
        # assertion is that only the OWNER's private notes are returned.
        async with self.Session() as db:
            rid = await self._reaction(db, visibility="public")
            mine = await svc.create_note(
                db, actor_id=self.owner, visibility="private",
                content="my private on entity", chemical_ids=[], reaction_ids=[rid])
            # another user's private note on the same entity
            await svc.create_note(
                db, actor_id=self.other, visibility="private",
                content="not mine", chemical_ids=[], reaction_ids=[rid])
            # my public note on the same entity
            await svc.create_note(
                db, actor_id=self.owner, visibility="public",
                content="my public on entity", chemical_ids=[], reaction_ids=[rid])
            await db.commit()

            result = await svc.list_my_notes(
                db, actor_id=self.owner, visibility="private",
                chemical_id=None, reaction_id=rid, page=1, page_size=20)
            self.assertEqual(result["total"], 1)
            self.assertEqual([item["id"] for item in result["items"]], [mine["id"]])

    async def test_p8_entity_filter_isolation(self):
        # list_my_notes with entity filter excludes notes not referencing it
        async with self.Session() as db:
            rid = await self._reaction(db, visibility="public")
            linked = await svc.create_note(
                db, actor_id=self.owner, visibility="private",
                content="linked", chemical_ids=[], reaction_ids=[rid])
            await svc.create_note(
                db, actor_id=self.owner, visibility="private",
                content="unlinked", chemical_ids=[], reaction_ids=[])
            await db.commit()

            filtered = await svc.list_my_notes(
                db, actor_id=self.owner, visibility="all",
                chemical_id=None, reaction_id=rid, page=1, page_size=20)
            self.assertEqual(filtered["total"], 1)
            self.assertEqual([item["id"] for item in filtered["items"]], [linked["id"]])


if __name__ == "__main__":
    unittest.main()
