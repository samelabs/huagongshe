-- The columns and relation tables below were introduced after the last
-- reactions statistics sample. Keep the planner informed without adding a
-- second overlapping owner index.
ANALYZE chemistry.reactions (created_by_user_id, visibility, moderation_status);
ANALYZE community.user_follows;
ANALYZE community.chemical_follows;
ANALYZE community.reaction_follows;
ANALYZE community.notifications;
ANALYZE community.user_api_tokens;
