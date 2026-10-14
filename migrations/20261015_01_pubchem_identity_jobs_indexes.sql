-- 2026-10-15 v1.7.2（生产 worker 领任务全表扫描事故）:
-- maintenance.pubchem_identity_jobs（生产约 25.6 万行, 全部终态）补齐与
-- cas_jobs 一致的两个部分索引:
--   1. lease_expiry: 服务 workapi_jobs 过期租约回收
--      UPDATE ... WHERE status='leased' AND lease_expires_at<=now()
--      —— 此前无可用索引, 每次领任务都全表扫描;
--   2. claim 索引: 服务领任务
--      SELECT ... WHERE status='queued' ORDER BY priority DESC, id LIMIT n
--      FOR UPDATE SKIP LOCKED
--      —— 旧 pubchem_identity_jobs_claim_idx(status, priority, id) 方向与
--      ORDER BY priority DESC, id 不一致, 提供不了排序, 本次替换为
--      (priority DESC, id) WHERE status='queued'（与 cas_jobs_claim_idx 同形）。
-- 表约 25 万行, 普通建索引秒级完成, 不用 CONCURRENTLY（runner 单事务内
-- 不可执行）; 幂等形式: DROP IF EXISTS + CREATE IF NOT EXISTS。

DROP INDEX IF EXISTS maintenance.pubchem_identity_jobs_claim_idx;

CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_claim_idx
    ON maintenance.pubchem_identity_jobs USING btree (priority DESC, id)
    WHERE (status = 'queued'::text);

CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_lease_expiry_idx
    ON maintenance.pubchem_identity_jobs USING btree (lease_expires_at, id)
    WHERE (status = 'leased'::text);

COMMENT ON INDEX maintenance.pubchem_identity_jobs_claim_idx IS
    'worker 领任务查询专用: SELECT ... WHERE status=''queued'' ORDER BY priority DESC, id LIMIT n FOR UPDATE SKIP LOCKED —— (priority DESC, id) 与 ORDER BY 同向免排序, 部分谓词只留 queued 行（与 cas_jobs_claim_idx 同形; 2026-10-15 替换旧 (status, priority, id) 索引, 其方向与 ORDER BY 不一致）';

COMMENT ON INDEX maintenance.pubchem_identity_jobs_lease_expiry_idx IS
    '过期租约回收查询专用: UPDATE ... WHERE status=''leased'' AND lease_expires_at<=now() —— 领任务前的回收此前无可用索引, 对全表（生产约 25.6 万行）顺序扫描（与 cas_jobs_lease_expiry_idx 同形）';
