-- HGS 通知链路补全个人事件（通知 = 提醒）。
-- 在既有两类「关注的人发布公开反应/笔记」之外, 新增两类个人相关事件:
--   new_follower        有人关注了你（收件人 = 被关注者）
--   reaction_favorited  有人收藏了你的公开反应（收件人 = 反应作者）
-- 化合物收藏仍只形成个人列表, 不产生通知（README「用户能力」边界同步更新）。
-- 仅放宽 event_type 取值: 复用现有列（actor_user_id / reaction_id / dedupe_key）,
-- 无新列、无回填 —— 两类新事件由写入侧（social.follow_user / follow_reaction）
-- 即时产生, 历史关注/收藏关系不补发通知。

ALTER TABLE community.notifications
    DROP CONSTRAINT notifications_event_type_check;
ALTER TABLE community.notifications
    ADD CONSTRAINT notifications_event_type_check
    CHECK (event_type IN ('new_reaction','new_note','new_follower','reaction_favorited'));
