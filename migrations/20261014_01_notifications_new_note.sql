-- HGS v1.7.1 I-007: 动态(activity feed)加入公开笔记(new_note)。
-- note_id 真实 FK + ON DELETE CASCADE: 笔记删除时通知行物理消失,
-- 列表/未读数无需为"已删除"特殊过滤; 改回私有/被隐藏由查询侧
-- visibility/moderation_status 条件表达(与 new_reaction 对齐)。

ALTER TABLE community.notifications
    ADD COLUMN IF NOT EXISTS note_id bigint
    REFERENCES community.notes(id) ON DELETE CASCADE;

ALTER TABLE community.notifications
    DROP CONSTRAINT notifications_event_type_check;
ALTER TABLE community.notifications
    ADD CONSTRAINT notifications_event_type_check
    CHECK (event_type IN ('new_reaction','new_note'));

-- 活动流索引去掉 event_type='new_reaction' 谓词: 两类事件同索引供给。
DROP INDEX IF EXISTS community.notifications_activity_feed_idx;
CREATE INDEX notifications_activity_feed_idx
    ON community.notifications (user_id, created_at DESC, id DESC);
