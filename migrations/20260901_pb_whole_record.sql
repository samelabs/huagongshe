-- PB链整记录化 migration (2026-09-01 方案: pb-whole-record-plan-2026-09-01.md)
-- 前置: worker 已停(pm2 stop)。API 在本 migration 与重启之间 SELECT 旧列会 500,
--       部署序背靠背执行(方案 A1-a, 分钟级窗口)。

BEGIN;

SET LOCAL statement_timeout = '600s';

-- ============================================================
-- 1. chemical_pubchem: 31 → 30 列
-- ============================================================

-- 删 6 列 (section 机制记账 + 冗余, 无内容损失)
ALTER TABLE chemistry.chemical_pubchem
    DROP COLUMN IF EXISTS section_fetched_at,
    DROP COLUMN IF EXISTS fetched_sections,
    DROP COLUMN IF EXISTS section_source_hashes,
    DROP COLUMN IF EXISTS expires_at,
    DROP COLUMN IF EXISTS source_hash,
    DROP COLUMN IF EXISTS schema_version;

-- 增 5 jsonb (38 字段, 实测 PUG View 来源; 存量空置, 随重拉自然填)
ALTER TABLE chemistry.chemical_pubchem
    ADD COLUMN IF NOT EXISTS external_ids jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ghs_codes    jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS exp_props    jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS exp_limits   jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS reactivity   jsonb NOT NULL DEFAULT '{}'::jsonb;

-- 存量时间重置: fetched_at 置 now() = 从今天起算 100 天窗 (防重拉风暴, 0901 裁定)
UPDATE chemistry.chemical_pubchem
SET    fetched_at = now(), updated_at = now()
WHERE  fetched_at IS NULL;

-- expires_at 索引随列已删; 不重建 (判窗=读点 fetched_at 点查, 不走索引)
DROP INDEX IF EXISTS chemistry.chemical_pubchem_expiry_idx;

-- ============================================================
-- 2. maintenance.pubchem_jobs: 列收窄 + 状态收窄 + 存量甄别归位
-- ============================================================

-- 2a. 历史 succeeded 出列不带入 (已完成)
DELETE FROM maintenance.pubchem_jobs WHERE status = 'succeeded';

-- 2b. 甄别规则 (0901 裁定, 数字为当时快照, 规则才是准绳):
--   丢弃: 无 cid 的历史多查询形态行 (inchikey_retired / not_found 无 cid)
--   丢弃: 数据层已有该行数据的 (cooldown 误杀中 135 条, 重拉无增益, 窗自然刷)
--   error 归位: pubchem_not_found 且有 cid → error 态留痕 (网络通内容空, 0901 裁定)
--   queued 归位: 其余全部 (cooldown 误杀 51k + retry + 网络类 + 杂项) → 重跑
DELETE FROM maintenance.pubchem_jobs j
WHERE  j.query_kind != 'cid'
   OR j.chemical_id IS NULL
   OR NOT EXISTS (SELECT 1 FROM chemistry.chemicals c
                  WHERE c.id = j.chemical_id AND c.pubchem_cid IS NOT NULL)
   OR EXISTS (SELECT 1 FROM chemistry.chemical_pubchem p
              WHERE p.chemical_id = j.chemical_id);

-- 2c. 状态与时间字段收窄 (not_before 行级调度退役, 0901 裁定三次)
UPDATE maintenance.pubchem_jobs
SET    status = CASE WHEN last_error_code = 'pubchem_not_found' THEN 'error' ELSE 'queued' END
WHERE status IN ('dead','failed','retry');
-- not_before NOT NULL 约束: 不改值, 列随后整列 DROP

-- 2d. 砍列
ALTER TABLE maintenance.pubchem_jobs
    DROP COLUMN IF EXISTS query_kind,
    DROP COLUMN IF EXISTS sections,
    DROP COLUMN IF EXISTS attempt_count,
    DROP COLUMN IF EXISTS max_attempts,
    DROP COLUMN IF EXISTS resolved_pubchem_cid,
    DROP COLUMN IF EXISTS result_hash,
    DROP COLUMN IF EXISTS result_summary,
    DROP COLUMN IF EXISTS heartbeat_at,
    DROP COLUMN IF EXISTS completed_at,
    DROP COLUMN IF EXISTS not_before;

-- 2e. 状态 CHECK 收窄: queued/leased/error (error=留痕占位, 复活走入列口翻态)
ALTER TABLE maintenance.pubchem_jobs DROP CONSTRAINT IF EXISTS pubchem_jobs_status_check;
ALTER TABLE maintenance.pubchem_jobs
    ADD CONSTRAINT pubchem_jobs_status_check
    CHECK (status = ANY (ARRAY['queued','leased','error']));

-- 2f. 索引: 只留 dedupe 唯一 (队列=瞬时小表, claim 全表扫足够; 0901 裁定)
DROP INDEX IF EXISTS maintenance.pubchem_jobs_claim_idx;
DROP INDEX IF EXISTS maintenance.pubchem_jobs_lease_expiry_idx;
DROP INDEX IF EXISTS maintenance.pubchem_jobs_completed_retention_idx;
DROP INDEX IF EXISTS maintenance.pubchem_jobs_chemical_idx;
DROP INDEX IF EXISTS maintenance.pubchem_jobs_active_dedupe_uidx;
CREATE UNIQUE INDEX pubchem_jobs_active_dedupe_uidx
    ON maintenance.pubchem_jobs (dedupe_key)
    WHERE status = ANY (ARRAY['queued','leased','error']);

COMMIT;
