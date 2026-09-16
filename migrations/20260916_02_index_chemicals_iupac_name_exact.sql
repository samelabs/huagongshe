-- 0916 第二阶段生产搜索修复: iupac_name exact B-tree。
--
-- 背景(生产实测 2026-09-16, main@672ea49, 第一阶段 preferred_name 索引后):
--   名称 exact 三源串行全查中的 iupac 路仍走 trgm GIN,
--   benzene iupac EXPLAIN before: Bitmap Index Scan 扫出 150,975 假阳性
--   候选 → 回表 37,136 heap blocks(recheck 剔 35,111) → 991.5ms(热态);
--   冷态/IO 争抢下单条即达 6,063ms(生产实测), 逼近 5s 局部闸/8s 全局闸,
--   第一阶段后 /api/search?q=benzene 仍 503(8.4s) 的主因。
--
-- 生产执行方式: CREATE INDEX CONCURRENTLY 已于生产直接先行执行(不锁写),
-- 之后 migration runner 对本文件为幂等 no-op(IF NOT EXISTS)。
-- fresh DB: 本文件即唯一来源, 通过 forward migration 正常创建索引。
--
-- 本文件不带 BEGIN/COMMIT, 也不含 CREATE INDEX CONCURRENTLY ——
-- runner 在单事务块内执行迁移, 而 CONCURRENTLY 不能运行在事务块中;
-- 故此处登记幂等形式(IF NOT EXISTS 的普通 CREATE INDEX), 与
-- 20260911_01 / 20260916_01 先例同款。
CREATE INDEX IF NOT EXISTS chemicals_iupac_name_exact_idx
    ON chemistry.chemicals (iupac_name, id)
    WHERE iupac_name IS NOT NULL;
