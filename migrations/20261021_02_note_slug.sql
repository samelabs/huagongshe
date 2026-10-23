-- 笔记 slug：URL 用 7 位小写字母数字随机值。
-- 存量回填与应用层同一字母表（a-z0-9），分配碰撞可恢复：每轮掷号后
-- 只保留无碰撞的分配，碰撞组作废进入下一轮重掷，直到全表唯一 ——
-- 唯一索引最后才建（若先建索引，回填撞号会直接失败且无法恢复）。
-- 掷号表达式必须是 7 个 substr 内联串联: 标量子查询形状在 PostgreSQL
-- 里每语句只求值一次, 全表会拿到同一个值, 回填循环永不收敛。

ALTER TABLE community.notes ADD COLUMN IF NOT EXISTS slug text;

DO $$
DECLARE
    alphabet constant text := 'abcdefghijklmnopqrstuvwxyz0123456789';
    collided int;
BEGIN
    LOOP
        UPDATE community.notes
        SET slug =
             substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
          || substr(alphabet, 1 + floor(random() * 36)::int, 1)
        WHERE slug IS NULL OR slug = '';

        -- 同号组全部作废（本轮新掷的之间、以及与既有已定值之间相撞同样处理）
        WITH collided_slugs AS (
            SELECT slug FROM community.notes
            WHERE slug IS NOT NULL
            GROUP BY slug HAVING count(*) > 1
        )
        UPDATE community.notes n
        SET slug = NULL
        FROM collided_slugs c
        WHERE n.slug = c.slug;

        GET DIAGNOSTICS collided = ROW_COUNT;
        EXIT WHEN collided = 0;
    END LOOP;
END $$;

ALTER TABLE community.notes ALTER COLUMN slug SET NOT NULL;

ALTER TABLE community.notes DROP CONSTRAINT IF EXISTS notes_slug_format;
ALTER TABLE community.notes
    ADD CONSTRAINT notes_slug_format CHECK (slug ~ '^[a-z0-9]{7}$');

CREATE UNIQUE INDEX IF NOT EXISTS notes_slug_key ON community.notes(slug);
