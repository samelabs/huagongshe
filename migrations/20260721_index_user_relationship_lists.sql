-- Keep profile relationship lists ordered without sorting an unbounded follow set.
CREATE INDEX CONCURRENTLY IF NOT EXISTS user_follows_follower_created_idx
  ON community.user_follows(follower_user_id,created_at DESC,followed_user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS user_follows_followed_created_idx
  ON community.user_follows(followed_user_id,created_at DESC,follower_user_id);
DROP INDEX CONCURRENTLY IF EXISTS community.user_follows_followed_idx;
CREATE INDEX CONCURRENTLY IF NOT EXISTS chemical_follows_user_created_idx
  ON community.chemical_follows(user_id,created_at DESC,chemical_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS reaction_follows_user_created_idx
  ON community.reaction_follows(user_id,created_at DESC,reaction_id);
