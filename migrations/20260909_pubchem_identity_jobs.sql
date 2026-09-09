-- §3 MVP: PubChem identity discovery 队列 (方案 A, InChIKey → candidate CID)
-- 基线 fd1fa06。职责边界: discovery 只产出候选证据, 永不写 chemicals 身份字段,
-- 永不 absorb/merge; 唯一出口 = 原子入既有 pubchem_jobs(query_value=CID),
-- 最终 identity authority 仍是 §2 frozen adjudication。

BEGIN;

SET LOCAL statement_timeout = '600s';

CREATE TABLE IF NOT EXISTS maintenance.pubchem_identity_jobs (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chemical_id      integer      NOT NULL,
    evidence_type    text         NOT NULL,   -- MVP 仅 'inchikey' (预留 smiles/cas)
    evidence_value   text         NOT NULL,   -- 标准键原文
    evidence_hash    text         NOT NULL,   -- sha256(evidence_value), 负缓存绑定
    status           text         NOT NULL DEFAULT 'queued',
        -- queued/leased/candidate/not_found/ambiguous/conflict/superseded/error
    priority         integer      NOT NULL DEFAULT 60,
    dedupe_key       text         NOT NULL,   -- f"disc:{chemical_id}:{type}:{hash}"
    result           jsonb,                   -- candidate_cid / cid_list / 详情
    request_context  jsonb,
    last_error_code  text,
    last_error_detail text,
    lease_owner      text,
    lease_token_hash bytea,
    lease_expires_at timestamptz,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    updated_at       timestamptz  NOT NULL DEFAULT now()
);

-- 全局唯一 dedupe(§3 修正1): 不用 partial — 同 evidence 全状态占位。
-- queued 幂等 / leased 不打断 / error 同请求翻态复活 /
-- 终态(candidate/not_found/ambiguous/superseded/conflict)不自动复活;
-- 新 evidence_hash = 新 dedupe_key = 新 job。
CREATE UNIQUE INDEX IF NOT EXISTS pubchem_identity_jobs_dedupe_idx
    ON maintenance.pubchem_identity_jobs (dedupe_key);

-- claim 只认 queued(对齐 pubchem_jobs 纪律: error 行留痕永不派发)。
CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_claim_idx
    ON maintenance.pubchem_identity_jobs (status, priority, id)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS pubchem_identity_jobs_chem_idx
    ON maintenance.pubchem_identity_jobs (chemical_id);

-- 无 FK: chemical_id 只作审计锚。行被 absorb 删除后历史 job 保留,
-- 追溯走 redirect/canonicalize 模型(与 chemical_identity_redirect 一致),
-- 不级联删除。

COMMIT;
