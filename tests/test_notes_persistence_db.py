"""v1.7.0 Notes persistence, privacy and identity-reference integration tests."""

from __future__ import annotations

import re
import unittest
import uuid
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ASYNC_URL = None
try:
    from tests.db_gate import test_db_or_skip

    _raw = test_db_or_skip()
except Exception:
    _raw = None

if _raw:
    _u = urlparse(_raw)
    assert parse_qs(_u.query).get("test_sentinel") in (["hgs-test-db"], ["hgs-ephemeral-db"])
    ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

from api.services import notes as svc
from api.services.identity import absorb


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class NotesPersistenceTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        self.user_ids: list[int] = []
        self.chemical_ids: list[int] = []
        self.reaction_ids: list[int] = []

        async with self.engine.begin() as conn:
            self.owner = await self._insert_user(conn, "owner")
            self.other = await self._insert_user(conn, "other")
            self.chemical = await self._insert_chemical(conn)
            self.public_reaction = await self._insert_reaction(
                conn, self.owner, visibility="public")
            self.private_reaction = await self._insert_reaction(
                conn, self.owner, visibility="private")
            self.foreign_private_reaction = await self._insert_reaction(
                conn, self.other, visibility="private")

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            if self.user_ids:
                await conn.execute(
                    text("DELETE FROM community.users WHERE id = ANY(:ids)"),
                    {"ids": self.user_ids},
                )
            if self.reaction_ids:
                await conn.execute(
                    text("DELETE FROM chemistry.reactions WHERE id = ANY(:ids)"),
                    {"ids": self.reaction_ids},
                )
            if self.chemical_ids:
                await conn.execute(
                    text("DELETE FROM chemistry.chemicals WHERE id = ANY(:ids)"),
                    {"ids": self.chemical_ids},
                )
        await self.engine.dispose()

    async def _insert_user(self, conn, suffix: str) -> int:
        row = (await conn.execute(text("""
            INSERT INTO community.users(username,email,password_hash,display_name)
            VALUES (:u,:e,'x',:d) RETURNING id
        """), {
            "u": f"note_{suffix}_{self.tag}",
            "e": f"note_{suffix}_{self.tag}@example.test",
            "d": f"Note {suffix}",
        })).scalar_one()
        value = int(row)
        self.user_ids.append(value)
        return value

    async def _insert_chemical(self, conn, cid: int | None = None) -> int:
        if cid is None:
            cid = 1_700_000_000 + int(uuid.uuid4().hex[:6], 16) % 100_000_000
        row = (await conn.execute(text("""
            INSERT INTO chemistry.chemicals(pubchem_cid,preferred_name,created_at,updated_at)
            VALUES (:cid,:name,now(),now()) RETURNING id
        """), {"cid": cid, "name": f"note-test-{self.tag}"})).scalar_one()
        value = int(row)
        self.chemical_ids.append(value)
        return value

    async def _insert_reaction(self, conn, owner: int, *, visibility: str) -> int:
        row = (await conn.execute(text("""
            INSERT INTO chemistry.reactions(
                created_by_user_id,visibility,moderation_status,created_via,source_type
            ) VALUES (:owner,:visibility,'visible','web','self')
            RETURNING id
        """), {"owner": owner, "visibility": visibility})).scalar_one()
        value = int(row)
        self.reaction_ids.append(value)
        return value

    async def test_private_note_supports_mixed_context_and_owner_read(self):
        async with self.Session() as db:
            note = await svc.create_note(
                db,
                actor_id=self.owner,
                visibility="private",
                content="route observation",
                chemical_ids=[self.chemical],
                reaction_ids=[self.private_reaction],
            )
            self.assertEqual(note["visibility"], "private")
            self.assertEqual(note["chemical_ids"], [self.chemical])
            self.assertEqual(note["reaction_ids"], [self.private_reaction])

            owner_view = await svc.get_note(db, note_id=note["id"], actor_id=self.owner)
            self.assertEqual(owner_view["content"], "route observation")
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.get_note(db, note_id=note["id"], actor_id=self.other)
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.get_note(db, note_id=note["id"], actor_id=None)

    async def test_foreign_private_reaction_is_fail_closed(self):
        async with self.Session() as db:
            with self.assertRaises(svc.NoteReferenceError) as ctx:
                await svc.create_note(
                    db,
                    actor_id=self.owner,
                    visibility="private",
                    content="must fail",
                    chemical_ids=[],
                    reaction_ids=[self.foreign_private_reaction],
                )
            self.assertIn("不存在或不可访问", str(ctx.exception))

    async def test_public_note_requires_public_visible_reactions(self):
        async with self.Session() as db:
            public_note = await svc.create_note(
                db,
                actor_id=self.owner,
                visibility="public",
                content="public context",
                chemical_ids=[self.chemical],
                reaction_ids=[self.public_reaction],
            )
            anonymous = await svc.get_note(db, note_id=public_note["id"], actor_id=None)
            self.assertEqual(anonymous["id"], public_note["id"])

            with self.assertRaises(svc.NoteReferenceError):
                await svc.create_note(
                    db,
                    actor_id=self.owner,
                    visibility="public",
                    content="must fail",
                    chemical_ids=[],
                    reaction_ids=[self.private_reaction],
                )

    async def test_private_to_public_revalidates_references(self):
        async with self.Session() as db:
            note = await svc.create_note(
                db,
                actor_id=self.owner,
                visibility="private",
                content="private context",
                chemical_ids=[],
                reaction_ids=[self.private_reaction],
            )
            with self.assertRaises(svc.NoteReferenceError):
                await svc.update_note(
                    db,
                    note_id=note["id"],
                    actor_id=self.owner,
                    visibility="public",
                    content="still private-linked",
                    chemical_ids=[],
                    reaction_ids=[self.private_reaction],
                )
            fresh = await svc.get_note(db, note_id=note["id"], actor_id=self.owner)
            self.assertEqual(fresh["visibility"], "private")

    async def test_entity_public_list_excludes_private_notes(self):
        async with self.Session() as db:
            private = await svc.create_note(
                db, actor_id=self.owner, visibility="private", content="private",
                chemical_ids=[self.chemical], reaction_ids=[])
            public = await svc.create_note(
                db, actor_id=self.owner, visibility="public", content="public",
                chemical_ids=[self.chemical], reaction_ids=[])
            page = await svc.list_entity_notes(
                db, entity="chemical", entity_id=self.chemical, page=1, page_size=20)
            ids = [item["id"] for item in page["items"]]
            self.assertIn(public["id"], ids)
            self.assertNotIn(private["id"], ids)

    async def test_reaction_delete_removes_reference_not_note(self):
        async with self.Session() as db:
            note = await svc.create_note(
                db, actor_id=self.owner, visibility="private", content="survives",
                chemical_ids=[], reaction_ids=[self.private_reaction])
            await db.execute(
                text("DELETE FROM chemistry.reactions WHERE id=:id"),
                {"id": self.private_reaction},
            )
            await db.commit()
            self.reaction_ids.remove(self.private_reaction)
            loaded = await svc.get_note(db, note_id=note["id"], actor_id=self.owner)
            self.assertEqual(loaded["reaction_ids"], [])
            self.assertEqual(loaded["content"], "survives")

    async def test_owner_delete_and_non_owner_delete(self):
        async with self.Session() as db:
            note = await svc.create_note(
                db, actor_id=self.owner, visibility="private", content="delete me",
                chemical_ids=[], reaction_ids=[])
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.delete_note(db, note_id=note["id"], actor_id=self.other)
            await svc.delete_note(db, note_id=note["id"], actor_id=self.owner)
            with self.assertRaises(svc.NoteNotAccessibleError):
                await svc.get_note(db, note_id=note["id"], actor_id=self.owner)

    async def test_identity_merge_rekeys_and_deduplicates_note_chemical_refs(self):
        cid = 1_850_000_000 + int(uuid.uuid4().hex[:6], 16) % 100_000_000
        async with self.engine.begin() as conn:
            a = await self._insert_chemical(conn, cid=cid)
            b = await self._insert_chemical(conn, cid=cid)

        async with self.Session() as db:
            note = await svc.create_note(
                db,
                actor_id=self.owner,
                visibility="private",
                content="identity reference",
                chemical_ids=[a, b],
                reaction_ids=[],
            )
            survivor = await absorb(
                db,
                source_id=a,
                target_id=b,
                reason="notes-identity-test",
                trigger="unit",
            )
            await db.commit()
            rows = (await db.execute(text("""
                SELECT chemical_id FROM community.note_chemicals
                WHERE note_id=:note_id
            """), {"note_id": note["id"]})).scalars().all()
            self.assertEqual([int(v) for v in rows], [survivor])
            if a != survivor and a in self.chemical_ids:
                self.chemical_ids.remove(a)
            if b != survivor and b in self.chemical_ids:
                self.chemical_ids.remove(b)


if __name__ == "__main__":
    unittest.main()
