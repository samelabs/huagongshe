-- Bound the personal activity feed by user and its displayed order.
CREATE INDEX CONCURRENTLY IF NOT EXISTS notifications_activity_feed_idx
  ON community.notifications(user_id,created_at DESC,id DESC)
  WHERE event_type='new_reaction';
