-- 校验 name_index_lang_check。
-- 单独成文件, 不与 20261015_03 同事务: VALIDATE CONSTRAINT 需要
-- SHARE UPDATE EXCLUSIVE 锁并全表扫描 —— 生产 name_index 约 1820 万行、
-- 6.9 GB, 预计分钟级耗时。该锁不阻塞读写(SELECT/INSERT/UPDATE 照常),
-- 只与其他 DDL/VACUUM 互斥; 若与 DROP/ADD 同处一个 --single-transaction,
-- 前面步骤拿到的 ACCESS EXCLUSIVE 会一直持有到事务结束, 扫描期间名称
-- 搜索与 worker 写入全部阻塞 —— 这正是拆分的原因。
-- 1820 万行现有值全部满足新约束(只有 'cn'/'en'), VALIDATE 必然通过。

ALTER TABLE chemistry.name_index VALIDATE CONSTRAINT name_index_lang_check;
