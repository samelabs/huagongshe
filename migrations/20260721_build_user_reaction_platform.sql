BEGIN;

ALTER TABLE community.users
  ADD COLUMN display_name text,
  ADD COLUMN bio text,
  ADD COLUMN avatar_path text,
  ADD COLUMN avatar_version text,
  ADD COLUMN email_verified_at timestamptz,
  ADD COLUMN last_login_at timestamptz;

UPDATE community.users SET display_name=username WHERE display_name IS NULL;
ALTER TABLE community.users ALTER COLUMN display_name SET NOT NULL;
ALTER TABLE community.users
  ADD CONSTRAINT users_display_name_length CHECK (char_length(display_name) BETWEEN 1 AND 80),
  ADD CONSTRAINT users_bio_length CHECK (bio IS NULL OR char_length(bio) <= 500);

UPDATE community.users SET role='member' WHERE role='editor';
ALTER TABLE community.users DROP CONSTRAINT users_role_check;
ALTER TABLE community.users
  ADD CONSTRAINT users_role_check CHECK (role IN ('member','admin'));

ALTER TABLE chemistry.reactions
  ADD COLUMN created_by_user_id bigint REFERENCES community.users(id) ON DELETE RESTRICT,
  ADD COLUMN visibility text NOT NULL DEFAULT 'public',
  ADD COLUMN moderation_status text NOT NULL DEFAULT 'visible',
  ADD COLUMN created_via text NOT NULL DEFAULT 'import',
  ADD COLUMN procedure_details text,
  ADD COLUMN conditions_detail text,
  ADD COLUMN temperature_value double precision,
  ADD COLUMN temperature_unit text,
  ADD COLUMN duration_value double precision,
  ADD COLUMN duration_unit text,
  ADD COLUMN ph double precision,
  ADD COLUMN atmosphere text,
  ADD COLUMN pressure_value double precision,
  ADD COLUMN pressure_unit text,
  ADD COLUMN workup_details text,
  ADD COLUMN safety_notes text,
  ADD COLUMN source_type text,
  ADD COLUMN doi text,
  ADD COLUMN patent text,
  ADD COLUMN source_url text,
  ADD COLUMN source_citation text,
  ADD COLUMN note text,
  ADD COLUMN idempotency_key text;

ALTER TABLE chemistry.reactions
  ADD CONSTRAINT reactions_visibility_check CHECK (visibility IN ('public','private')) NOT VALID,
  ADD CONSTRAINT reactions_moderation_status_check CHECK (moderation_status IN ('visible','hidden')) NOT VALID,
  ADD CONSTRAINT reactions_created_via_check CHECK (created_via IN ('import','web','agent')) NOT VALID,
  ADD CONSTRAINT reactions_temperature_unit_check CHECK (temperature_unit IS NULL OR temperature_unit IN ('CELSIUS','KELVIN')) NOT VALID,
  ADD CONSTRAINT reactions_duration_unit_check CHECK (duration_unit IS NULL OR duration_unit IN ('MINUTE','HOUR','DAY')) NOT VALID,
  ADD CONSTRAINT reactions_ph_check CHECK (ph IS NULL OR (ph >= 0 AND ph <= 14)) NOT VALID,
  ADD CONSTRAINT reactions_source_type_check CHECK (source_type IS NULL OR source_type IN ('self','doi','patent','database','url','other')) NOT VALID,
  ADD CONSTRAINT reactions_user_source_check CHECK (created_by_user_id IS NULL OR source_type IS NOT NULL) NOT VALID;

CREATE INDEX reactions_owner_visibility_idx
  ON chemistry.reactions(created_by_user_id,visibility,id DESC)
  WHERE created_by_user_id IS NOT NULL;
CREATE UNIQUE INDEX reactions_owner_idempotency_uidx
  ON chemistry.reactions(created_by_user_id,idempotency_key)
  WHERE created_by_user_id IS NOT NULL AND idempotency_key IS NOT NULL;

ALTER TABLE chemistry.reaction_chemicals
  ADD COLUMN amount_value double precision,
  ADD COLUMN amount_unit text,
  ADD COLUMN equivalents double precision,
  ADD COLUMN concentration_value double precision,
  ADD COLUMN concentration_unit text,
  ADD COLUMN yield_percent double precision;

ALTER TABLE chemistry.reaction_chemicals
  ADD CONSTRAINT reaction_chemicals_amount_check CHECK (amount_value IS NULL OR amount_value >= 0) NOT VALID,
  ADD CONSTRAINT reaction_chemicals_equivalents_check CHECK (equivalents IS NULL OR equivalents >= 0) NOT VALID,
  ADD CONSTRAINT reaction_chemicals_concentration_check CHECK (concentration_value IS NULL OR concentration_value >= 0) NOT VALID,
  ADD CONSTRAINT reaction_chemicals_yield_check CHECK (yield_percent IS NULL OR (yield_percent >= 0 AND yield_percent <= 100)) NOT VALID;

ALTER TABLE chemistry.reaction_chemicals DROP CONSTRAINT reaction_chemicals_reaction_fkey;
ALTER TABLE chemistry.reaction_chemicals
  ADD CONSTRAINT reaction_chemicals_reaction_fkey
  FOREIGN KEY (reaction_id) REFERENCES chemistry.reactions(id) ON DELETE CASCADE NOT VALID;

CREATE TABLE community.user_api_tokens (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  token_hash bytea NOT NULL UNIQUE,
  token_prefix text NOT NULL,
  scopes text[] NOT NULL DEFAULT ARRAY['read','reaction:write']::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  last_used_at timestamptz,
  revoked_at timestamptz,
  CHECK (scopes <@ ARRAY['read','reaction:write']::text[])
);
CREATE INDEX user_api_tokens_user_idx ON community.user_api_tokens(user_id,created_at DESC);

CREATE TABLE community.user_follows (
  follower_user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  followed_user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (follower_user_id,followed_user_id),
  CHECK (follower_user_id <> followed_user_id)
);
CREATE INDEX user_follows_followed_idx ON community.user_follows(followed_user_id,follower_user_id);

CREATE TABLE community.chemical_follows (
  user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  chemical_id integer NOT NULL REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id,chemical_id)
);
CREATE INDEX chemical_follows_chemical_idx ON community.chemical_follows(chemical_id,user_id);

CREATE TABLE community.reaction_follows (
  user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  reaction_id bigint NOT NULL REFERENCES chemistry.reactions(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id,reaction_id)
);
CREATE INDEX reaction_follows_reaction_idx ON community.reaction_follows(reaction_id,user_id);

CREATE TABLE community.notifications (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  event_type text NOT NULL CHECK (event_type IN ('new_reaction','reaction_updated')),
  actor_user_id bigint REFERENCES community.users(id) ON DELETE SET NULL,
  reaction_id bigint REFERENCES chemistry.reactions(id) ON DELETE CASCADE,
  chemical_id integer REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
  dedupe_key text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz
);
CREATE INDEX notifications_user_idx ON community.notifications(user_id,read_at,created_at DESC);

ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_visibility_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_moderation_status_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_created_via_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_temperature_unit_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_duration_unit_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_ph_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_source_type_check;
ALTER TABLE chemistry.reactions VALIDATE CONSTRAINT reactions_user_source_check;
ALTER TABLE chemistry.reaction_chemicals VALIDATE CONSTRAINT reaction_chemicals_amount_check;
ALTER TABLE chemistry.reaction_chemicals VALIDATE CONSTRAINT reaction_chemicals_equivalents_check;
ALTER TABLE chemistry.reaction_chemicals VALIDATE CONSTRAINT reaction_chemicals_concentration_check;
ALTER TABLE chemistry.reaction_chemicals VALIDATE CONSTRAINT reaction_chemicals_yield_check;
ALTER TABLE chemistry.reaction_chemicals VALIDATE CONSTRAINT reaction_chemicals_reaction_fkey;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM community.chemical_submissions LIMIT 1) THEN
    RAISE EXCEPTION 'chemical_submissions is not empty; explicit migration required';
  END IF;
  IF EXISTS (SELECT 1 FROM community.reaction_submissions LIMIT 1) THEN
    RAISE EXCEPTION 'reaction_submissions is not empty; explicit migration required';
  END IF;
END $$;

DROP TABLE community.reaction_submission_participants;
DROP TABLE community.reaction_submissions;
DROP TABLE community.chemical_submissions;
DROP TABLE community.reaction_help;

COMMIT;
