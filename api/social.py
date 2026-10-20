"""Explicit follow lists and notifications from followed users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text

from .core.database import get_db
from .core.security import Actor, current_actor, current_session
from .services.chemicals import attach_localized_names

router = APIRouter(tags=["follows"])

# 通知过滤条件唯一事实源 —— 通知列表(social)与 dashboard 未读数(users)
# 共用, 保证「未读数 = 列表里未读的条数」。
# 四类事件（通知 = 提醒）:
#   new_reaction / new_note   关注的人发布公开反应/笔记 —— 发布时扇出给关注者;
#                             要求关注关系仍成立、通知晚于关注时间、客体公开可见
#                             （取关后不再续旧事件, 已投递的随客体隐藏条件消失）。
#   new_follower              有人关注了你 —— 收件人=被关注者, 事件即事实,
#                             不要求关注关系仍成立。
#   reaction_favorited        有人收藏了你的公开反应 —— 收件人=反应作者,
#                             客体转私有/隐藏后随之消失。
# 化合物收藏仍只形成个人列表, 不产生通知（README 边界）。
_ACTIVITY_FEED_JOINS = """
        JOIN community.users u ON u.id=n.actor_user_id AND u.status='active'
        LEFT JOIN chemistry.reactions r ON r.id=n.reaction_id
        LEFT JOIN community.notes nt ON nt.id=n.note_id
        LEFT JOIN community.user_follows f
          ON f.follower_user_id=n.user_id AND f.followed_user_id=n.actor_user_id
         AND n.created_at>=f.created_at
"""
_ACTIVITY_FEED_VISIBLE = """
            n.user_id=:id
          AND (
            (n.event_type='new_reaction'
             AND r.visibility='public' AND r.moderation_status='visible'
             AND f.follower_user_id IS NOT NULL)
            OR (n.event_type='new_note'
             AND nt.visibility='public' AND nt.moderation_status='visible'
             AND f.follower_user_id IS NOT NULL)
            OR n.event_type='new_follower'
            OR (n.event_type='reaction_favorited'
             AND r.visibility='public' AND r.moderation_status='visible')
          )
"""


async def unread_activity_count(db, user_id: int) -> int:
    """活动流可见且未读的条数(与 /users/me/notifications 同一过滤)。"""
    return int((await db.execute(text(f"""
        SELECT count(*) FROM community.notifications n
        {_ACTIVITY_FEED_JOINS}
        WHERE {_ACTIVITY_FEED_VISIBLE} AND n.read_at IS NULL
    """), {"id": user_id})).scalar() or 0)


@router.post("/users/{username}/follow", status_code=204)
async def follow_user(username: str, actor: Actor = Depends(current_session), db=Depends(get_db)):
    target = (await db.execute(text("""
        SELECT id FROM community.users WHERE lower(username)=lower(:username) AND status='active'
    """), {"username": username})).scalar()
    if target is None:
        raise HTTPException(404, {"message": "用户不存在", "kind": "user_not_found"})
    if int(target) == actor.id:
        raise HTTPException(409, {"message": "不能关注自己", "kind": "cannot_follow_self"})
    await db.execute(text("""
        INSERT INTO community.user_follows(follower_user_id,followed_user_id)
        VALUES (:actor,:target) ON CONFLICT DO NOTHING
    """), {"actor": actor.id, "target": target})
    # 个人事项通知: 有人关注了你（dedupe 挡取关-再关注重复打扰）
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,dedupe_key)
        VALUES (:target,'new_follower',:actor,
                'new-follower:' || :target_text || ':' || :actor_text)
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "target": target, "actor": actor.id,
        "target_text": str(target), "actor_text": str(actor.id),
    })
    await db.commit()


@router.delete("/users/{username}/follow", status_code=204)
async def unfollow_user(username: str, actor: Actor = Depends(current_session), db=Depends(get_db)):
    await db.execute(text("""
        DELETE FROM community.user_follows f USING community.users u
        WHERE f.follower_user_id=:actor AND f.followed_user_id=u.id
          AND lower(u.username)=lower(:username)
    """), {"actor": actor.id, "username": username})
    await db.commit()


@router.post("/chemicals/{chemical_id}/follow", status_code=204)
async def follow_chemical(chemical_id: int = Path(..., ge=1, le=2_147_483_647), actor: Actor = Depends(current_session), db=Depends(get_db)):
    exists = (await db.execute(text("SELECT 1 FROM chemistry.chemicals WHERE id=:id"), {"id": chemical_id})).scalar()
    if not exists:
        raise HTTPException(404, {"message": "化合物不存在", "kind": "chemical_not_found"})
    await db.execute(text("""
        INSERT INTO community.chemical_follows(user_id,chemical_id)
        VALUES (:user_id,:chemical_id) ON CONFLICT DO NOTHING
    """), {"user_id": actor.id, "chemical_id": chemical_id})
    await db.commit()


@router.delete("/chemicals/{chemical_id}/follow", status_code=204)
async def unfollow_chemical(chemical_id: int = Path(..., ge=1, le=2_147_483_647), actor: Actor = Depends(current_session), db=Depends(get_db)):
    await db.execute(text("""
        DELETE FROM community.chemical_follows WHERE user_id=:user_id AND chemical_id=:chemical_id
    """), {"user_id": actor.id, "chemical_id": chemical_id})
    await db.commit()


@router.post("/reactions/{reaction_id}/follow", status_code=204)
async def follow_reaction(reaction_id: int = Path(..., ge=1, le=2_147_483_647), actor: Actor = Depends(current_session), db=Depends(get_db)):
    row = (await db.execute(text("""
        SELECT created_by_user_id,visibility,moderation_status
        FROM chemistry.reactions WHERE id=:id
    """), {"id": reaction_id})).fetchone()
    if not row or row[1] != "public" or row[2] != "visible":
        raise HTTPException(404, {"message": "公开反应不存在", "kind": "public_reaction_not_found"})
    if row[0] == actor.id:
        raise HTTPException(409, {"message": "无需关注自己创建的反应", "kind": "own_reaction_no_follow"})
    await db.execute(text("""
        INSERT INTO community.reaction_follows(user_id,reaction_id)
        VALUES (:user_id,:reaction_id) ON CONFLICT DO NOTHING
    """), {"user_id": actor.id, "reaction_id": reaction_id})
    # 个人事项通知: 有人收藏了你的公开反应（收件人=作者; endpoint 已挡自己收藏自己）。
    # 导入反应无作者(created_by_user_id 为空), 无人可通知。
    if row[0] is not None:
        await db.execute(text("""
            INSERT INTO community.notifications
              (user_id,event_type,actor_user_id,reaction_id,dedupe_key)
            VALUES (:owner,'reaction_favorited',:actor,:reaction_id,
                    'reaction-favorited:' || :owner_text || ':' || :actor_text || ':' || :reaction_text)
            ON CONFLICT (dedupe_key) DO NOTHING
        """), {
            "owner": row[0], "actor": actor.id, "reaction_id": reaction_id,
            "owner_text": str(row[0]), "actor_text": str(actor.id), "reaction_text": str(reaction_id),
        })
    await db.commit()


@router.delete("/reactions/{reaction_id}/follow", status_code=204)
async def unfollow_reaction(reaction_id: int = Path(..., ge=1, le=2_147_483_647), actor: Actor = Depends(current_session), db=Depends(get_db)):
    await db.execute(text("""
        DELETE FROM community.reaction_follows WHERE user_id=:user_id AND reaction_id=:reaction_id
    """), {"user_id": actor.id, "reaction_id": reaction_id})
    await db.commit()


@router.get("/users/me/follows/chemicals")
async def followed_chemicals(
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(40, ge=1, le=100),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    total = int((await db.execute(text("""
        SELECT count(*) FROM community.chemical_follows WHERE user_id=:id
    """), {"id": actor.id})).scalar() or 0)
    rows = (await db.execute(text("""
        SELECT c.id,c.preferred_name,c.iupac_name,c.molecular_formula,c.smiles,f.created_at
        FROM community.chemical_follows f JOIN chemistry.chemicals c ON c.id=f.chemical_id
        WHERE f.user_id=:id ORDER BY f.created_at DESC,c.id
        LIMIT :page_size OFFSET :offset
    """), {
        "id": actor.id, "page_size": page_size, "offset": (page - 1) * page_size,
    })).mappings().all()
    items = [dict(row) for row in rows]
    # name_cn 唯一来源: services.chemicals.attach_localized_names —— 本地化名
    # 索引的 (kind,lang,source) owner; social 层不建第二套 taxonomy。
    await attach_localized_names(db, items)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/users/me/follows/reactions")
async def followed_reactions(
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(40, ge=1, le=100),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    total = int((await db.execute(text("""
        SELECT count(*) FROM community.reaction_follows f
        JOIN chemistry.reactions r ON r.id=f.reaction_id
        WHERE f.user_id=:id AND r.visibility='public' AND r.moderation_status='visible'
    """), {"id": actor.id})).scalar() or 0)
    rows = (await db.execute(text("""
        SELECT r.id,r.reaction_smiles,r.updated_at,f.created_at
        FROM community.reaction_follows f JOIN chemistry.reactions r ON r.id=f.reaction_id
        WHERE f.user_id=:id AND r.visibility='public' AND r.moderation_status='visible'
        ORDER BY f.created_at DESC,r.id
        LIMIT :page_size OFFSET :offset
    """), {
        "id": actor.id, "page_size": page_size, "offset": (page - 1) * page_size,
    })).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/users/me/notifications")
async def notifications(
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(50, ge=1, le=100),
    actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    offset = (page - 1) * page_size
    total = int((await db.execute(text(f"""
        SELECT count(*) FROM community.notifications n
        {_ACTIVITY_FEED_JOINS}
        WHERE {_ACTIVITY_FEED_VISIBLE}
    """), {"id": actor.id})).scalar() or 0)
    rows = (await db.execute(text(f"""
        SELECT n.id,n.event_type,n.reaction_id,n.chemical_id,n.note_id,
               n.created_at,n.read_at,
               CASE WHEN n.event_type='new_note'
                    THEN left(split_part(nt.content, E'\\n', 1), 140)
                    ELSE NULL END AS note_excerpt,
               u.username AS actor_username,u.display_name AS actor_display_name,
               u.avatar_path AS actor_avatar_url,(u.status='active') AS actor_active
        FROM community.notifications n
        {_ACTIVITY_FEED_JOINS}
        WHERE {_ACTIVITY_FEED_VISIBLE}
        ORDER BY n.created_at DESC,n.id DESC LIMIT :limit OFFSET :offset
    """), {
        "id": actor.id, "limit": page_size, "offset": offset,
    })).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/users/me/notifications/read", status_code=204)
async def read_notifications(actor: Actor = Depends(current_session), db=Depends(get_db)):
    await db.execute(text("""
        UPDATE community.notifications SET read_at=now() WHERE user_id=:id AND read_at IS NULL
    """), {"id": actor.id})
    await db.commit()
