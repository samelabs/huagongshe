-- CB cas_jobs 同构归位 (2026-09-01 方案: 与 pubchem_jobs 统一形态)
-- dead cpp 类 = ChemicalBook EN 变体页 0831-0901 故障期打死, 源已恢复, 全部复活重跑。
-- 丢弃口径: cas_fetch_error/cb_governor_cooldown 等通道类死行也复活(通道故障非任务问题);
--          多语言行要求寻址键 cb_number 存在(无号不可执行, cb_number_missing 教训)。

BEGIN;

SET LOCAL statement_timeout = '600s';

-- 历史成功出列不带入
DELETE FROM maintenance.cas_jobs WHERE status = 'succeeded';

-- 多语言无 cb_number 的行丢弃 (寻址键缺失, 不可执行; 168974d 已剥该 error 分支)
DELETE FROM maintenance.cas_jobs j
WHERE  j.request_context->>'locale' IS DISTINCT FROM 'zh-CN'
   AND NOT EXISTS (SELECT 1 FROM chemistry.chemicals c
                   WHERE c.id = j.chemical_id AND c.cb_number IS NOT NULL);

-- 非成功全部归位 queued (dead/failed/retry → 重跑; not_before 行级调度退役)
UPDATE maintenance.cas_jobs
SET    status = 'queued'
WHERE status IN ('dead','failed','retry');
-- not_before NOT NULL 约束: 不改值, 列随后整列 DROP

-- 砍列 (与 pubchem_jobs 同构)
ALTER TABLE maintenance.cas_jobs
    DROP COLUMN IF EXISTS attempt_count,
    DROP COLUMN IF EXISTS max_attempts,
    DROP COLUMN IF EXISTS heartbeat_at,
    DROP COLUMN IF EXISTS completed_at,
    DROP COLUMN IF EXISTS not_before;

-- CHECK 收窄
ALTER TABLE maintenance.cas_jobs DROP CONSTRAINT IF EXISTS cas_jobs_status_check;
ALTER TABLE maintenance.cas_jobs
    ADD CONSTRAINT cas_jobs_status_check
    CHECK (status = ANY (ARRAY['queued','leased','error']));

-- 索引: 只留 dedupe 唯一
DROP INDEX IF EXISTS maintenance.cas_jobs_claim_idx;
DROP INDEX IF EXISTS maintenance.cas_jobs_lease_expiry_idx;
CREATE UNIQUE INDEX cas_jobs_active_dedupe_uidx
    ON maintenance.cas_jobs (dedupe_key)
    WHERE status = ANY (ARRAY['queued','leased','error']);

COMMIT;
