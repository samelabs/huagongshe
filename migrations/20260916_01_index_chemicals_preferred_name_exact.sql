-- 0916 第一阶段生产搜索修复: preferred_name exact B-tree。
--
-- 背景(生产实测 2026-09-16, main@672ea49):
--   名称 exact 等值查询(preferred_name = ANY(...))只有 trgm GIN 可走,
--   benzene 单条 EXPLAIN: Bitmap Index Scan 扫出 144,534 假阳性候选 →
--   回表 36,077 heap blocks(recheck 剔 33,774) → 952ms(热态); 冷缓存/
--   IO 争抢下撞 8s statement_timeout → /api/search 503。
--   甲醇事故(517c81d, 0913)同型: planner 为 ORDER BY id+LIMIT 弃 GIN 走
--   id 索引全扫滤 173 万行。B-tree 等值两条死法都治。
--
-- 生产执行方式: CREATE INDEX CONCURRENTLY 已于生产直接先行执行(不锁写),
-- 之后 migration runner 对本文件为幂等 no-op(IF NOT EXISTS)。
-- fresh DB: 本文件即唯一来源, 通过 forward migration 正常创建索引。
--
-- 本文件不带 BEGIN/COMMIT, 也不含 CREATE INDEX CONCURRENTLY ——
-- runner 在单事务块内执行迁移, 而 CONCURRENTLY 不能运行在事务块中;
-- 故此处登记幂等形式(IF NOT EXISTS 的普通 CREATE INDEX), 与
-- 20260911_01 的先例同款。
CREATE INDEX IF NOT EXISTS chemicals_preferred_name_exact_idx
    ON chemistry.chemicals (preferred_name, id)
    WHERE preferred_name IS NOT NULL;
