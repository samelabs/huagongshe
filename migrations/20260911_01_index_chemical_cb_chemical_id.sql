-- 0911: chemical_cb 补 chemical_id 非部分索引。
--
-- 背景(实测): chemical_cb 原有索引为
--   chemical_cb_pkey(id)
--   chemical_cb_legacy_null_uidx(chemical_id, locale)      WHERE cb_number IS NULL
--   chemical_cb_source_grain_uidx(chemical_id, cb_number, locale) WHERE cb_number IS NOT NULL
-- 两个 chemical_id 前缀索引都是**部分索引**, 无法服务裸谓词 `chemical_id = $1`
-- (谓词不蕴含索引条件) → 以下路径全部退化为 1.27GB 并行顺序扫:
--   · ON DELETE CASCADE 的 RI 触发器 probe (实测 544ms/行, 删 1280 父行需 >18 分钟)
--   · identity absorb 的引用表改指
--   · 任何按 chemical_id 定位的查询/校验
--
-- 本文件只做一件事: 建非部分索引。不带 BEGIN/COMMIT(runner 单事务执行)。
-- production 上该 DDL 以 CREATE INDEX CONCURRENTLY 先行执行(不锁写),
-- 之后 migration runner 对本文件为幂等 no-op(IF NOT EXISTS)。
-- 不触碰任何现有 partial unique index。
CREATE INDEX IF NOT EXISTS idx_chemical_cb_chemical_id
    ON chemistry.chemical_cb (chemical_id);
