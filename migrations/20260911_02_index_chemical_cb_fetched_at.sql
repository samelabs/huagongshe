-- 0911: chemical_cb 补 (fetched_at DESC NULLS LAST) 索引, 服务 /admin/pipeline latest-10。
--
-- 背景(实测, production):
--   SELECT chemical_id, locale, last_status, fetched_at
--     FROM chemistry.chemical_cb
--    ORDER BY fetched_at DESC NULLS LAST
--    LIMIT 10;
--   → Parallel Seq Scan(1,389,652 行 / 1308 MB) + top-N 排序,
--     Execution 1156.7 ms, Buffers hit 16,747 / read 125,028。
--   该表此前**没有任何 fetched_at 索引**(全库 fetched_at 索引数 = 0)。
--
-- 索引列序与方向必须与查询逐字一致: DESC NULLS LAST
--   (只写 fetched_at 会得到 ASC NULLS LAST, 无法直接服务 DESC 排序)
--
-- 本文件只做一件事, 不带 BEGIN/COMMIT(runner 单事务执行)。
-- production 上该 DDL 以 CREATE INDEX CONCURRENTLY 先行执行(不锁写),
-- 之后 migration runner 对本文件为幂等 no-op(IF NOT EXISTS)。
CREATE INDEX IF NOT EXISTS idx_chemical_cb_fetched_at
    ON chemistry.chemical_cb (fetched_at DESC NULLS LAST);
