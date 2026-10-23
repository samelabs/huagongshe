-- 笔记模型扩容：可选标题 + 阅读量。
-- 公开态客观化：visibility 本就是纯客观列；表内仅有 created_at/updated_at
-- 两个时间戳，不存在「公开发布时间」列，公开转化只产生通知事件、不落时间戳。
-- 化合物/反应关联沿用既有 note_chemicals / note_reactions 专用 ref 表。

ALTER TABLE community.notes ADD COLUMN IF NOT EXISTS title text;

ALTER TABLE community.notes DROP CONSTRAINT IF EXISTS notes_title_length;
ALTER TABLE community.notes
    ADD CONSTRAINT notes_title_length
    CHECK (title IS NULL OR char_length(title) BETWEEN 1 AND 120);

ALTER TABLE community.notes ADD COLUMN IF NOT EXISTS view_count bigint NOT NULL DEFAULT 0;
