"""Notes domain service.

Notes are independent user-owned context records. They may reference HCID/HRID,
but those references do not own the Note lifecycle.

This module is transport-neutral: no FastAPI/MCP imports.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


class NoteNotAccessibleError(Exception):
    """Note is missing or not readable/mutable by the current actor."""


class NoteReferenceError(Exception):
    """One or more requested entity references are invalid or inaccessible."""


class NoteEntityNotFoundError(Exception):
    """Entity-scoped public Note query target does not exist or is not public."""


def _page_payload(items: list[dict[str, Any]], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {"items": items, "total": int(total), "page": page, "page_size": page_size}


async def _reference_maps(
    db,
    note_ids: list[int],
    *,
    viewer_id: int | None,
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Load references without leaking reactions that became private later.

    Reference access is evaluated at read time. A Note may have been created
    while a reaction was public and the reaction owner may later make it
    private/hidden. Public Note serialization must not expose that HRID after
    the transition. A signed-in viewer may still see a private reaction
    reference only when they own that reaction.
    """
    chemicals: dict[int, list[int]] = {note_id: [] for note_id in note_ids}
    reactions: dict[int, list[int]] = {note_id: [] for note_id in note_ids}
    if not note_ids:
        return chemicals, reactions

    chemical_rows = (await db.execute(text("""
        SELECT note_id, chemical_id
        FROM community.note_chemicals
        WHERE note_id = ANY(:ids)
        ORDER BY note_id, chemical_id
    """), {"ids": note_ids})).all()
    reaction_rows = (await db.execute(text("""
        SELECT nr.note_id, nr.reaction_id,
               r.created_by_user_id, r.visibility, r.moderation_status
        FROM community.note_reactions nr
        JOIN chemistry.reactions r ON r.id=nr.reaction_id
        WHERE nr.note_id = ANY(:ids)
        ORDER BY nr.note_id, nr.reaction_id
    """), {"ids": note_ids})).mappings().all()

    for note_id, chemical_id in chemical_rows:
        chemicals[int(note_id)].append(int(chemical_id))
    for row in reaction_rows:
        public_visible = (
            row["visibility"] == "public"
            and row["moderation_status"] == "visible"
        )
        owned = (
            viewer_id is not None
            and row["created_by_user_id"] is not None
            and int(row["created_by_user_id"]) == viewer_id
        )
        if public_visible or owned:
            reactions[int(row["note_id"])].append(int(row["reaction_id"]))
    return chemicals, reactions


async def _hydrate_rows(
    db,
    rows,
    *,
    viewer_id: int | None,
) -> list[dict[str, Any]]:
    mapped = [dict(row) for row in rows]
    ids = [int(row["id"]) for row in mapped]
    chemical_refs, reaction_refs = await _reference_maps(
        db, ids, viewer_id=viewer_id)
    for row in mapped:
        note_id = int(row["id"])
        row["chemical_ids"] = chemical_refs.get(note_id, [])
        row["reaction_ids"] = reaction_refs.get(note_id, [])
        if "owner_user_id" in row:
            row["owner_user_id"] = int(row["owner_user_id"])
    return mapped


async def _validate_references(
    db,
    *,
    actor_id: int,
    visibility: str,
    chemical_ids: list[int],
    reaction_ids: list[int],
) -> None:
    if chemical_ids:
        existing = set(int(v) for v in (await db.execute(text("""
            SELECT id FROM chemistry.chemicals WHERE id = ANY(:ids)
        """), {"ids": chemical_ids})).scalars().all())
        if existing != set(chemical_ids):
            raise NoteReferenceError("一个或多个化合物不存在")

    if not reaction_ids:
        return

    rows = (await db.execute(text("""
        SELECT id, created_by_user_id, visibility, moderation_status
        FROM chemistry.reactions
        WHERE id = ANY(:ids)
    """), {"ids": reaction_ids})).mappings().all()

    by_id = {int(row["id"]): row for row in rows}
    if set(by_id) != set(reaction_ids):
        raise NoteReferenceError("一个或多个反应不存在或不可访问")

    for reaction_id in reaction_ids:
        row = by_id[reaction_id]
        public_visible = (
            row["visibility"] == "public"
            and row["moderation_status"] == "visible"
        )
        owned = row["created_by_user_id"] is not None and int(row["created_by_user_id"]) == actor_id
        if visibility == "public":
            if not public_visible:
                raise NoteReferenceError("公开笔记只能关联公开可见的反应")
        elif not (public_visible or owned):
            raise NoteReferenceError("一个或多个反应不存在或不可访问")


async def _replace_references(
    db,
    *,
    note_id: int,
    chemical_ids: list[int],
    reaction_ids: list[int],
) -> None:
    await db.execute(text("DELETE FROM community.note_chemicals WHERE note_id=:id"), {"id": note_id})
    await db.execute(text("DELETE FROM community.note_reactions WHERE note_id=:id"), {"id": note_id})
    for chemical_id in chemical_ids:
        await db.execute(text("""
            INSERT INTO community.note_chemicals(note_id, chemical_id)
            VALUES (:note_id, :chemical_id)
        """), {"note_id": note_id, "chemical_id": chemical_id})
    for reaction_id in reaction_ids:
        await db.execute(text("""
            INSERT INTO community.note_reactions(note_id, reaction_id)
            VALUES (:note_id, :reaction_id)
        """), {"note_id": note_id, "reaction_id": reaction_id})


async def create_note(
    db,
    *,
    actor_id: int,
    visibility: str,
    content: str,
    chemical_ids: list[int],
    reaction_ids: list[int],
) -> dict[str, Any]:
    await _validate_references(
        db,
        actor_id=actor_id,
        visibility=visibility,
        chemical_ids=chemical_ids,
        reaction_ids=reaction_ids,
    )
    try:
        note_id = int((await db.execute(text("""
            INSERT INTO community.notes(owner_user_id, visibility, content)
            VALUES (:owner, :visibility, :content)
            RETURNING id
        """), {
            "owner": actor_id,
            "visibility": visibility,
            "content": content,
        })).scalar_one())
        await _replace_references(
            db,
            note_id=note_id,
            chemical_ids=chemical_ids,
            reaction_ids=reaction_ids,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_note(db, note_id=note_id, actor_id=actor_id)


async def get_note(db, *, note_id: int, actor_id: int | None) -> dict[str, Any]:
    row = (await db.execute(text("""
        SELECT n.id,n.owner_user_id,n.visibility,n.moderation_status,n.content,
               n.created_at,n.updated_at,u.username,u.display_name
        FROM community.notes n
        JOIN community.users u ON u.id=n.owner_user_id AND u.status='active'
        WHERE n.id=:id
          AND (
            n.owner_user_id=:actor
            OR (n.visibility='public' AND n.moderation_status='visible')
          )
    """), {"id": note_id, "actor": actor_id or 0})).mappings().first()
    if row is None:
        raise NoteNotAccessibleError("笔记不存在")
    return (await _hydrate_rows(db, [row], viewer_id=actor_id))[0]


async def update_note(
    db,
    *,
    note_id: int,
    actor_id: int,
    visibility: str,
    content: str,
    chemical_ids: list[int],
    reaction_ids: list[int],
) -> dict[str, Any]:
    current = (await db.execute(text("""
        SELECT owner_user_id
        FROM community.notes
        WHERE id=:id
        FOR UPDATE
    """), {"id": note_id})).first()
    if current is None or int(current[0]) != actor_id:
        raise NoteNotAccessibleError("笔记不存在")

    await _validate_references(
        db,
        actor_id=actor_id,
        visibility=visibility,
        chemical_ids=chemical_ids,
        reaction_ids=reaction_ids,
    )
    try:
        await db.execute(text("""
            UPDATE community.notes
            SET visibility=:visibility, content=:content, updated_at=now()
            WHERE id=:id
        """), {
            "id": note_id,
            "visibility": visibility,
            "content": content,
        })
        await _replace_references(
            db,
            note_id=note_id,
            chemical_ids=chemical_ids,
            reaction_ids=reaction_ids,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_note(db, note_id=note_id, actor_id=actor_id)


async def delete_note(db, *, note_id: int, actor_id: int) -> None:
    result = await db.execute(text("""
        DELETE FROM community.notes
        WHERE id=:id AND owner_user_id=:owner
        RETURNING id
    """), {"id": note_id, "owner": actor_id})
    if result.scalar() is None:
        await db.rollback()
        raise NoteNotAccessibleError("笔记不存在")
    await db.commit()


async def list_my_notes(
    db,
    *,
    actor_id: int,
    visibility: str,
    chemical_id: int | None,
    reaction_id: int | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    conditions = ["n.owner_user_id=:owner"]
    params: dict[str, Any] = {
        "owner": actor_id,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    if visibility != "all":
        conditions.append("n.visibility=:visibility")
        params["visibility"] = visibility
    if chemical_id is not None:
        conditions.append("""
            EXISTS (
              SELECT 1 FROM community.note_chemicals nc
              WHERE nc.note_id=n.id AND nc.chemical_id=:chemical_id
            )
        """)
        params["chemical_id"] = chemical_id
    if reaction_id is not None:
        conditions.append("""
            EXISTS (
              SELECT 1 FROM community.note_reactions nr
              WHERE nr.note_id=n.id AND nr.reaction_id=:reaction_id
            )
        """)
        params["reaction_id"] = reaction_id

    where = " AND ".join(conditions)
    total = int((await db.execute(text(f"""
        SELECT count(*) FROM community.notes n WHERE {where}
    """), params)).scalar() or 0)
    rows = (await db.execute(text(f"""
        SELECT n.id,n.owner_user_id,n.visibility,n.moderation_status,n.content,
               n.created_at,n.updated_at,u.username,u.display_name
        FROM community.notes n
        JOIN community.users u ON u.id=n.owner_user_id
        WHERE {where}
        ORDER BY n.updated_at DESC,n.id DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    return _page_payload(await _hydrate_rows(db, rows, viewer_id=actor_id), total, page, page_size)


async def list_entity_notes(
    db,
    *,
    entity: str,
    entity_id: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if entity == "chemical":
        exists = (await db.execute(text("""
            SELECT 1 FROM chemistry.chemicals WHERE id=:id
        """), {"id": entity_id})).scalar()
        if not exists:
            raise NoteEntityNotFoundError("化合物不存在")
        join = "JOIN community.note_chemicals ref ON ref.note_id=n.id"
        predicate = "ref.chemical_id=:entity_id"
    elif entity == "reaction":
        exists = (await db.execute(text("""
            SELECT 1 FROM chemistry.reactions
            WHERE id=:id AND visibility='public' AND moderation_status='visible'
        """), {"id": entity_id})).scalar()
        if not exists:
            raise NoteEntityNotFoundError("反应不存在")
        join = "JOIN community.note_reactions ref ON ref.note_id=n.id"
        predicate = "ref.reaction_id=:entity_id"
    else:
        raise ValueError(f"unsupported note entity: {entity}")

    params = {
        "entity_id": entity_id,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    total = int((await db.execute(text(f"""
        SELECT count(*)
        FROM community.notes n
        {join}
        WHERE {predicate}
          AND n.visibility='public'
          AND n.moderation_status='visible'
    """), params)).scalar() or 0)
    rows = (await db.execute(text(f"""
        SELECT n.id,n.owner_user_id,n.visibility,n.moderation_status,n.content,
               n.created_at,n.updated_at,u.username,u.display_name
        FROM community.notes n
        {join}
        JOIN community.users u ON u.id=n.owner_user_id AND u.status='active'
        WHERE {predicate}
          AND n.visibility='public'
          AND n.moderation_status='visible'
        ORDER BY n.updated_at DESC,n.id DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    return _page_payload(await _hydrate_rows(db, rows, viewer_id=None), total, page, page_size)
