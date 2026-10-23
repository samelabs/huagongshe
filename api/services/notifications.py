"""Notification domain — 通知读写单一 owner（transport-neutral）。

通知 = 收件人收件箱（提醒），不是某个展示场景的附属品：
读写状态（read_at）逐条存在，读取操作与列表/未读数同源过滤，
保证「未读数 = 列表里未读的条数」恒成立。

职责（唯一 owner）:
- 事件词表 EVENT_TYPES（与 DB CHECK 约束同一取值集合）
- 写入: 四类事件的扇出/单发（safely 变体自带独立事务与 1s 超时预算，
  不进核心写事务）
- 读取: 列表（含动态可见性过滤）/ 未读数 / 单条已读 / 全量已读

不职责: HTTP 映射（social.py 端点层）、dashboard 组装（users.py）、
前端表达（web 工作台通知面板）。

四类事件（投递语义见各写入函数 docstring）:
  new_reaction / new_note   关注的人发布公开反应/笔记 —— 发布时扇出给关注者
  new_follower              有人关注了你 —— 收件人=被关注者
  reaction_favorited        有人收藏了你的公开反应 —— 收件人=反应作者

未来接入新事件类型 = 放宽 DB CHECK + 本文件加一个写入函数 +
前端通知卡加渲染分支；读取侧四操作不需要任何改动。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# 事件词表单一权威（migrations 中 notifications_event_type_check 同集合）
EVENT_TYPES = ("new_reaction", "new_note", "new_follower", "reaction_favorited")

# 列表/未读数共用的可见性过滤 —— 同一 SQL 事实源保证口径一致：
# 关注类事件要求关注关系仍成立且通知晚于关注时间、客体公开可见
# （取关后不再续旧事件, 已投递的随客体隐藏条件消失）。
_FEED_JOINS = """
        JOIN community.users u ON u.id=n.actor_user_id AND u.status='active'
        LEFT JOIN chemistry.reactions r ON r.id=n.reaction_id
        LEFT JOIN community.notes nt ON nt.id=n.note_id
        LEFT JOIN community.user_follows f
          ON f.follower_user_id=n.user_id AND f.followed_user_id=n.actor_user_id
         AND n.created_at>=f.created_at
"""
_FEED_VISIBLE = """
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


# ---------------------------------------------------------------------------
# 读取侧
# ---------------------------------------------------------------------------

async def list_notifications(db, user_id: int, *, page: int, page_size: int) -> dict:
    """收件人通知列表（新→旧）。read_at 逐条返回，已读/未读由消费方表达。"""
    offset = (page - 1) * page_size
    total = int((await db.execute(text(f"""
        SELECT count(*) FROM community.notifications n
        {_FEED_JOINS}
        WHERE {_FEED_VISIBLE}
    """), {"id": user_id})).scalar() or 0)
    rows = (await db.execute(text(f"""
        SELECT n.id,n.event_type,n.reaction_id,n.chemical_id,n.note_id,nt.slug AS note_slug,
               n.created_at,n.read_at,
               CASE WHEN n.event_type='new_note'
                    THEN left(split_part(nt.content, E'\\n', 1), 140)
                    ELSE NULL END AS note_excerpt,
               u.username AS actor_username,u.display_name AS actor_display_name,
               u.avatar_path AS actor_avatar_url,(u.status='active') AS actor_active
        FROM community.notifications n
        {_FEED_JOINS}
        WHERE {_FEED_VISIBLE}
        ORDER BY n.created_at DESC,n.id DESC LIMIT :limit OFFSET :offset
    """), {
        "id": user_id, "limit": page_size, "offset": offset,
    })).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def unread_count(db, user_id: int) -> int:
    """可见且未读的条数（与 list_notifications 同一过滤）。"""
    return int((await db.execute(text(f"""
        SELECT count(*) FROM community.notifications n
        {_FEED_JOINS}
        WHERE {_FEED_VISIBLE} AND n.read_at IS NULL
    """), {"id": user_id})).scalar() or 0)


async def mark_read(db, user_id: int, notification_id: int) -> bool:
    """单条已读。已读是收件人对自己收件箱的操作，按所有权判定，
    与该条当前是否在动态流可见无关（隐藏条目本就不可见，全量已读兜底）。
    返回 False = 不存在或不属于该用户（→404）；已读再读幂等返回 True。"""
    owned = (await db.execute(text(
        "SELECT 1 FROM community.notifications WHERE id=:nid AND user_id=:uid"
    ), {"nid": notification_id, "uid": user_id})).scalar()
    if not owned:
        return False
    await db.execute(text("""
        UPDATE community.notifications SET read_at=now()
        WHERE id=:nid AND user_id=:uid AND read_at IS NULL
    """), {"nid": notification_id, "uid": user_id})
    return True


async def mark_all_read(db, user_id: int) -> None:
    """全量已读（含动态流不可见的残留行，避免它们永远挂着未读）。"""
    await db.execute(text("""
        UPDATE community.notifications SET read_at=now()
        WHERE user_id=:id AND read_at IS NULL
    """), {"id": user_id})


# ---------------------------------------------------------------------------
# 写入侧（事务由调用方持有；safely 变体自带独立事务）
# ---------------------------------------------------------------------------

async def notify_new_follower(db, target_id: int, actor_id: int) -> None:
    """有人关注了你（dedupe 挡取关-再关注重复打扰）。事务由调用方提交。"""
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,dedupe_key)
        VALUES (:target,'new_follower',:actor,
                'new-follower:' || :target_text || ':' || :actor_text)
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "target": target_id, "actor": actor_id,
        "target_text": str(target_id), "actor_text": str(actor_id),
    })


async def notify_reaction_favorited(db, owner_id: int, actor_id: int, reaction_id: int) -> None:
    """有人收藏了你的公开反应（收件人=作者；endpoint 已挡自己收藏自己）。
    导入反应无作者时调用方跳过。事务由调用方提交。"""
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,reaction_id,dedupe_key)
        VALUES (:owner,'reaction_favorited',:actor,:reaction_id,
                'reaction-favorited:' || :owner_text || ':' || :actor_text || ':' || :reaction_text)
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "owner": owner_id, "actor": actor_id, "reaction_id": reaction_id,
        "owner_text": str(owner_id), "actor_text": str(actor_id),
        "reaction_text": str(reaction_id),
    })


async def notify_new_reaction(db, actor_id: int, reaction_id: int) -> None:
    """公开反应扇出给关注者（dedupe 挡重；客体可见性由读取侧过滤表达）。"""
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,reaction_id,dedupe_key)
        SELECT follower_user_id,'new_reaction',:actor_id,:reaction_id,
               'new-reaction:' || follower_user_id::text || ':' || :reaction_id_text
        FROM community.user_follows
        WHERE followed_user_id=:actor_id AND follower_user_id<>:actor_id
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "actor_id": actor_id, "reaction_id": reaction_id, "reaction_id_text": str(reaction_id),
    })


async def notify_new_reaction_safely(db, actor_id: int, reaction_id: int) -> None:
    """Keep auxiliary activity fan-out outside and below the core write budget."""
    try:
        await db.execute(text("SET LOCAL statement_timeout='1000ms'"))
        await notify_new_reaction(db, actor_id, reaction_id)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "reaction activity notification skipped",
            exc_info=True,
            extra={"actor_id": actor_id, "reaction_id": reaction_id},
        )


async def notify_new_note(db, owner_id: int, note_id: int) -> None:
    """公开笔记扇出给关注者（与 notify_new_reaction 同构）。

    dedupe_key 挡重: 私有→公开→私有→公开 只通知一次; 笔记转回私有/被
    隐藏/删除时由动态查询的 join 条件(join notes visibility/moderation)
    或 FK CASCADE 物理消除, 不需要撤回通知。
    """
    await db.execute(text("""
        INSERT INTO community.notifications
          (user_id,event_type,actor_user_id,note_id,dedupe_key)
        SELECT follower_user_id,'new_note',:owner_id,:note_id,
               'new-note:' || follower_user_id::text || ':' || :note_id_text
        FROM community.user_follows
        WHERE followed_user_id=:owner_id AND follower_user_id<>:owner_id
        ON CONFLICT (dedupe_key) DO NOTHING
    """), {
        "owner_id": owner_id, "note_id": note_id, "note_id_text": str(note_id),
    })


async def notify_new_note_safely(db, owner_id: int, note_id: int) -> None:
    """辅助 fan-out 不进核心写预算（与 notify_new_reaction_safely 同构）。"""
    try:
        await db.execute(text("SET LOCAL statement_timeout='1000ms'"))
        await notify_new_note(db, owner_id, note_id)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "note activity notification skipped",
            exc_info=True,
            extra={"owner_id": owner_id, "note_id": note_id},
        )
