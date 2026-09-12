-- 2026-09-12 Worker trusted write plane: completion receipt。
--
-- 目的(P0-2/P1-5): complete 的 protocol acknowledgement idempotency +
-- 最小成功归因。primary completion 事务内同事务写入; job DELETE 后,
-- 同 worker + 同 lease_token_hash 重试 complete 凭 receipt 得幂等 ack。
--
-- 只存协议事实, 不存原始 token / payload / 大 JSON / HTML。
-- retention: 简单时间保留 — completed_at 早于保留窗的行由既有维护
-- 习惯(手动/巡检脚本)按 completed_at 删除, 不建 daemon/service;
-- 保留窗默认覆盖协议重试窗口(nonce TTL 600s)与故障调查窗口。

CREATE TABLE IF NOT EXISTS maintenance.workapi_completion_receipts (
    family           text        NOT NULL,   -- 'pubchem' | 'cas' | 'identity'
    job_id           bigint      NOT NULL,
    worker_id        text        NOT NULL,
    lease_token_hash bytea       NOT NULL,
    scope            text        NOT NULL,   -- 授权 scope 快照: 'pubchem' | 'cas'
    terminal_status  text        NOT NULL,   -- 'ok' | 'not_found' | 'empty' | 'standalone' | ...
    chemical_id      integer,                -- 最终 chemical / survivor (可空)
    completed_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (family, job_id)
);

CREATE INDEX IF NOT EXISTS idx_workapi_receipts_completed_at
    ON maintenance.workapi_completion_receipts (completed_at);
