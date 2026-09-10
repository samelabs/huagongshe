-- 2026-09-10 cutover reconciliation:
-- production 缺少 maintenance.pubchem_identity_jobs(cutover 只读核查证实)。
-- 本文件是 cutover 后第一条 forward migration, 只负责把 existing production
-- 与 0000_baseline 目标状态对齐; fresh baseline 库中表已存在, 全部 no-op。
-- DDL 语义与 migrations/history/20260909_pubchem_identity_jobs.sql 及
-- 0000_baseline.sql 的最终 schema 一致; 不新增字段/不改 discovery semantics/
-- 不 backfill/不 enqueue historical rows。

SET LOCAL statement_timeout = '600s';

CREATE TABLE IF NOT EXISTS maintenance.pubchem_identity_jobs (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chemical_id      integer      NOT NULL,
    evidence_type    text         NOT NULL,
    evidence_value   text         NOT NULL,
    evidence_hash    text         NOT NULL,
    status           text         NOT NULL DEFAULT 'queued',
    priority         integer      NOT NULL DEFAULT 60,
    dedupe_key       text         NOT NULL,
    result           jsonb,
    request_context  jsonb,
    last_error_code  text,
    last_error_detail text,
    lease_owner      text,
    lease_token_hash bytea,
    lease_expires_at timestamptz,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    updated_at       timestamptz  NOT NULL DEFAULT now()
);

-- 全局唯一 dedupe: 同 evidence 全状态占位。
CREATE UNIQUE INDEX IF NOT EXISTS pubchem_identity_jobs_dedupe_idx
    ON maintenance.pubchem_identity_jobs (dedupe_key);

-- claim 只认 queued。
CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_claim_idx
    ON maintenance.pubchem_identity_jobs (status, priority, id)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_chem_idx
    ON maintenance.pubchem_identity_jobs (chemical_id);
