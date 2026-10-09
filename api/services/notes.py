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
    """One or more requested entity references are invalid or inaccessible.

    kind 是稳定机器码(v1.7.0 L2: 前端按 kind 做五语言分类提示, 不解析
    中文 detail 原文); str(exc) 保持中文原文, adapter 层将 HTTP 400
    detail 升级为 {message, kind} 结构。
    - chemical_not_found: 部分 HCID 不存在
    - reaction_not_accessible: HRID 不存在/不可访问(含非 owner 私有)
    - public_requires_public: 公开笔记关联了非公开可见反应
    """

    kind: str = "reaction_not_accessible"

    def __init__(self, detail: str, *, kind: str | None = None):
        super().__init__(detail)
        if kind is not None:
            self.kind = kind


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
            raise NoteReferenceError(
                "一个或多个化合物不存在", kind="chemical_not_found")

    if not reaction_ids:
        return

    rows = (await db.execute(text("""
        SELECT id, created_by_user_id, visibility, moderation_status
        FROM chemistry.reactions
        WHERE id = ANY(:ids)
    """), {"ids": reaction_ids})).mappings().all()

    by_id = {int(row["id"]): row for row in rows}
    if set(by_id) != set(reaction_ids):
        raise NoteReferenceError(
            "一个或多个反应不存在或不可访问", kind="reaction_not_accessible")

    for reaction_id in reaction_ids:
        row = by_id[reaction_id]
        public_visible = (
            row["visibility"] == "public"
            and row["moderation_status"] == "visible"
        )
        owned = row["created_by_user_id"] is not None and int(row["created_by_user_id"]) == actor_id
        # v1.7.0 权限边界收口: 非所有者 + 非公开可见 → 统一
        # reaction_not_accessible, 与 HRID 不存在不可区分(不泄露存在性);
        # 无论笔记可见性与 HRID 是否真实存在。
        if not public_visible and not owned:
            raise NoteReferenceError(
                "一个或多个反应不存在或不可访问",
                kind="reaction_not_accessible")
        if visibility == "public" and not public_visible:
            # 仅所有者会走到这里(自己的非公开 HRID 进公开笔记): 保留
            # 准确提示, 所有者本就知道该反应存在, 无泄露。
            raise NoteReferenceError(
                "公开笔记只能关联公开可见的反应",
                kind="public_requires_public")


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
    # G2/P-1: hidden notes 404 for everyone (including the owner); private
    # notes only for the owning session; public+visible notes anonymously.
    # Inactive owners 404 via the users join.
    row = (await db.execute(text("""
        SELECT n.id,n.owner_user_id,n.visibility,n.moderation_status,n.content,
               n.created_at,n.updated_at,u.username,u.display_name
        FROM community.notes n
        JOIN community.users u ON u.id=n.owner_user_id AND u.status='active'
        WHERE n.id=:id
          AND n.moderation_status='visible'
          AND (
            n.owner_user_id=:actor
            OR n.visibility='public'
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
    # R5: access check BEFORE any write. The row-locking read must apply the
    # same G2 visibility rule as reads: hidden notes and inactive owners are
    # 404 for everyone, so an update can never commit and only then 404 —
    # and a hidden note can never be mutated back into visibility.
    current = (await db.execute(text("""
        SELECT n.owner_user_id
        FROM community.notes n
        JOIN community.users u ON u.id=n.owner_user_id AND u.status='active'
        WHERE n.id=:id
          AND n.moderation_status='visible'
        FOR UPDATE OF n
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
    # Same G2 rule as read/update (R5): hidden notes and inactive owners are
    # 404 for everyone — the owner cannot delete a hidden note either.
    result = await db.execute(text("""
        DELETE FROM community.notes n
        USING community.users u
        WHERE n.id=:id
          AND n.owner_user_id=:owner
          AND u.id=n.owner_user_id AND u.status='active'
          AND n.moderation_status='visible'
        RETURNING n.id
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
    # R5: hidden notes must not appear as unopenable cards in the owner's
    # own list (reads 404 for everyone) — exclude them at the source.
    conditions = ["n.owner_user_id=:owner", "n.moderation_status='visible'"]
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


async def list_public_user_notes(
    db,
    *,
    user_id: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Public notes of one active user, for the public profile page.

    G2: only visibility='public' AND moderation_status='visible' AND
    active owner rows are returned; reference serialization reuses the
    shared read-time privacy filtering (no private HRID leak).
    """
    params: dict[str, Any] = {
        "owner": user_id,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    base_where = """
        n.owner_user_id=:owner
        AND n.visibility='public'
        AND n.moderation_status='visible'
    """
    total = int((await db.execute(text(f"""
        SELECT count(*)
        FROM community.notes n
        JOIN community.users u ON u.id=n.owner_user_id AND u.status='active'
        WHERE {base_where}
    """), params)).scalar() or 0)
    rows = (await db.execute(text(f"""
        SELECT n.id,n.owner_user_id,n.visibility,n.moderation_status,n.content,
               n.created_at,n.updated_at,u.username,u.display_name
        FROM community.notes n
        JOIN community.users u ON u.id=n.owner_user_id AND u.status='active'
        WHERE {base_where}
        ORDER BY n.updated_at DESC,n.id DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    return _page_payload(await _hydrate_rows(db, rows, viewer_id=None), total, page, page_size)


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
        JOIN community.users u
          ON u.id=n.owner_user_id AND u.status='active'
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
