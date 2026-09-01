-- 数据链收口 migration (2026-09-01, DATA_CHAIN_REFACTOR_PLAN §6)
-- 一次性: CHECK 收窄 + 索引重建 + 沉积清理 + events DROP。
-- 全部 <30 万行级, 毫秒~秒级; 停 worker 后执行。

BEGIN;

-- 1) 沉积清理(先清数据再收窄 CHECK, 避免 CHECK 挡道)
DELETE FROM maintenance.pubchem_jobs
    WHERE status IN ('succeeded','failed','dead','retry');
DELETE FROM maintenance.cas_jobs
    WHERE status IN ('succeeded','failed','dead','retry');

-- 2) events 表 DROP (FK 级联已随 job 行删除; 表整体退役)
DROP TABLE IF EXISTS maintenance.pubchem_job_events;

-- 3) 数据层: error 存量删除(值域收敛 ok/not_found)
DELETE FROM chemistry.chemical_cb WHERE last_status='error';

-- 4) 每表 DDL (两 job 表对称)
-- pubchem_jobs
ALTER TABLE maintenance.pubchem_jobs DROP CONSTRAINT IF EXISTS pubchem_jobs_status_check;
ALTER TABLE maintenance.pubchem_jobs ADD CONSTRAINT pubchem_jobs_status_check
    CHECK (status = ANY (ARRAY['queued','leased','error']));
DROP INDEX IF EXISTS maintenance.pubchem_jobs_active_dedupe_uidx;
CREATE UNIQUE INDEX pubchem_jobs_active_dedupe_uidx
    ON maintenance.pubchem_jobs (dedupe_key)
    WHERE status = ANY (ARRAY['queued','leased','error']);
DROP INDEX IF EXISTS maintenance.pubchem_jobs_claim_idx;
CREATE INDEX pubchem_jobs_claim_idx
    ON maintenance.pubchem_jobs (priority DESC, not_before, id)
    WHERE status = ANY (ARRAY['queued','error']);
DROP INDEX IF EXISTS maintenance.pubchem_jobs_completed_retention_idx;
ALTER TABLE maintenance.pubchem_jobs DROP CONSTRAINT IF EXISTS pubchem_jobs_max_attempts_check;
ALTER TABLE maintenance.pubchem_jobs DROP COLUMN IF EXISTS max_attempts;

-- cas_jobs
ALTER TABLE maintenance.cas_jobs DROP CONSTRAINT IF EXISTS cas_jobs_status_check;
ALTER TABLE maintenance.cas_jobs ADD CONSTRAINT cas_jobs_status_check
    CHECK (status = ANY (ARRAY['queued','leased','error']));
DROP INDEX IF EXISTS maintenance.cas_jobs_active_dedupe_uidx;
CREATE UNIQUE INDEX cas_jobs_active_dedupe_uidx
    ON maintenance.cas_jobs (dedupe_key)
    WHERE status = ANY (ARRAY['queued','leased','error']);
DROP INDEX IF EXISTS maintenance.cas_jobs_claim_idx;
CREATE INDEX cas_jobs_claim_idx
    ON maintenance.cas_jobs (priority DESC, not_before, id)
    WHERE status = ANY (ARRAY['queued','error']);
DROP INDEX IF EXISTS maintenance.cas_jobs_completed_retention_idx;
ALTER TABLE maintenance.cas_jobs DROP CONSTRAINT IF EXISTS cas_jobs_max_attempts_check;
ALTER TABLE maintenance.cas_jobs DROP COLUMN IF EXISTS max_attempts;

COMMIT;
