-- Skills 底座：用户私有/平台公开的技能容器（DB 索引 + FS 内容存储）。
-- 决策依据（2026-08-16 定稿）：
--   * 用户 skill 恒 private；visibility='public' 仅平台账号（role=admin）可写。
--   * 存量 token 一次性补 skill:write，禁重建 token。
BEGIN;

CREATE TABLE community.skills (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_id        bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
  slug            text NOT NULL,
  title           text NOT NULL,
  description     text NOT NULL DEFAULT '',
  license         text NOT NULL DEFAULT 'MIT',
  category        text,
  origin          text NOT NULL DEFAULT 'user',
  visibility      text NOT NULL DEFAULT 'private',
  has_scripts     boolean NOT NULL DEFAULT false,
  file_count      int NOT NULL DEFAULT 0,
  size_bytes      bigint NOT NULL DEFAULT 0,
  idempotency_key text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE community.skills
  ADD CONSTRAINT skills_slug_check CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
  ADD CONSTRAINT skills_title_length CHECK (char_length(title) BETWEEN 1 AND 120),
  ADD CONSTRAINT skills_description_length CHECK (char_length(description) <= 500),
  ADD CONSTRAINT skills_origin_check CHECK (origin IN ('user','official','kdense')),
  ADD CONSTRAINT skills_visibility_check CHECK (visibility IN ('private','public')),
  ADD CONSTRAINT skills_file_count_range CHECK (file_count BETWEEN 0 AND 128),
  ADD CONSTRAINT skills_size_range CHECK (size_bytes BETWEEN 0 AND 10485760);

CREATE UNIQUE INDEX skills_owner_slug_idx ON community.skills(owner_id, slug);

CREATE INDEX skills_public_list_idx ON community.skills(category, updated_at DESC)
  WHERE visibility = 'public';

CREATE INDEX skills_owner_updated_idx ON community.skills(owner_id, updated_at DESC);

CREATE TABLE community.skill_files (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  skill_id   bigint NOT NULL REFERENCES community.skills(id) ON DELETE CASCADE,
  path       text NOT NULL,
  is_text    boolean NOT NULL,
  size_bytes int NOT NULL,
  sha256     text NOT NULL,
  is_entry   boolean NOT NULL DEFAULT false
);

ALTER TABLE community.skill_files
  ADD CONSTRAINT skill_files_path_check CHECK (
    path ~ '^([a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)*)?$'
    AND path NOT LIKE '%..%'
  ),
  ADD CONSTRAINT skill_files_size_range CHECK (size_bytes BETWEEN 0 AND 2097152),
  ADD CONSTRAINT skill_files_text_only CHECK (is_text OR path LIKE 'assets/%' OR path LIKE 'examples/%');

CREATE UNIQUE INDEX skill_files_skill_path_idx ON community.skill_files(skill_id, path);

-- ── token scopes：CHECK 放行 skill:write，DEFAULT 含 skill:write，
--    存量一次性回填。三个动作必须同 migration 完成，禁分批。
ALTER TABLE community.user_api_tokens
  DROP CONSTRAINT user_api_tokens_scopes_check;

ALTER TABLE community.user_api_tokens
  ADD CONSTRAINT user_api_tokens_scopes_check
    CHECK (scopes <@ ARRAY['read'::text, 'reaction:write'::text, 'skill:write'::text]);

ALTER TABLE community.user_api_tokens
  ALTER COLUMN scopes SET DEFAULT ARRAY['read','reaction:write','skill:write']::text[];

UPDATE community.user_api_tokens
   SET scopes = array_append(scopes, 'skill:write')
 WHERE NOT ('skill:write' = ANY (scopes));

COMMIT;
