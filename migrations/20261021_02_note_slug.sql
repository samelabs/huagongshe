-- 笔记 slug（2026-10-21 裁定）：URL 用 7 位小写字母数字随机值。
-- 存量回填 md5 前缀（[0-9a-f] ⊂ 小写字母数字）；应用层新生成用全字母表。

ALTER TABLE community.notes ADD COLUMN IF NOT EXISTS slug text;

UPDATE community.notes
SET slug = substr(md5(random()::text || id::text || clock_timestamp()::text), 1, 7)
WHERE slug IS NULL OR slug = '';

ALTER TABLE community.notes ALTER COLUMN slug SET NOT NULL;

ALTER TABLE community.notes DROP CONSTRAINT IF EXISTS notes_slug_format;
ALTER TABLE community.notes
    ADD CONSTRAINT notes_slug_format CHECK (slug ~ '^[a-z0-9]{7}$');

CREATE UNIQUE INDEX IF NOT EXISTS notes_slug_key ON community.notes(slug);
