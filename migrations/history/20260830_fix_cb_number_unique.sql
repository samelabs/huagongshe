-- 20260830_fix_cb_number_unique.sql
-- 修复: chemicals_cb_number_uidx 唯一断言错误。
-- 现实模型: CB 按 CAS 建页, 1 CAS → 1 cb_number → N 个 CID 行合法共享;
-- CID 才是真区分键, CAS/cb_number 都不区分(实例: 5680-79-5 三行)。
-- 原 UNIQUE 索引导致同 CAS 后到的 CID 行永远写不进印记并报 UniqueViolation。
-- 改法: 唯一 → 普通(查询用), 保留部分索引形态便于点查。
DROP INDEX IF EXISTS chemistry.chemicals_cb_number_uidx;
CREATE INDEX IF NOT EXISTS chemicals_cb_number_idx
    ON chemistry.chemicals (cb_number) WHERE (cb_number IS NOT NULL);
