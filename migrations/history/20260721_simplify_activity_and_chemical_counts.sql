BEGIN;

DELETE FROM community.notifications WHERE event_type <> 'new_reaction';
ALTER TABLE community.notifications DROP CONSTRAINT IF EXISTS notifications_event_type_check;
ALTER TABLE community.notifications
  ADD CONSTRAINT notifications_event_type_check CHECK (event_type = 'new_reaction');

COMMIT;

CREATE INDEX CONCURRENTLY IF NOT EXISTS reactions_excluded_from_public_idx
  ON chemistry.reactions(id)
  WHERE visibility <> 'public' OR moderation_status <> 'visible';
