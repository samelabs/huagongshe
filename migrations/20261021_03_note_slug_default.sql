-- 笔记 slug 列默认值：任何不带 slug 的 INSERT（历史调用方/测试夹具）
-- 由数据库生成 7 位随机值兜底。与应用层同一字母表（a-z0-9）；掷号
-- 函数跳过已占用的值（碰撞可恢复），唯一索引仍是对并发缝的最终兜底。
-- 应用层（services/notes.py）仍显式生成 slug。

CREATE OR REPLACE FUNCTION community.note_slug_default() RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    alphabet constant text := 'abcdefghijklmnopqrstuvwxyz0123456789';
    candidate text;
BEGIN
    LOOP
        SELECT
             substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
        INTO candidate;
        EXIT WHEN NOT EXISTS (SELECT 1 FROM community.notes WHERE slug = candidate);
    END LOOP;
    RETURN candidate;
END $$;

ALTER TABLE community.notes
    ALTER COLUMN slug
    SET DEFAULT community.note_slug_default();
