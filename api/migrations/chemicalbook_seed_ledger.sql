-- ingestion control-plane: ChemicalBook source seed ledger (0907)
-- 职责边界(立项冻结): source assertion 账本, 不是 identity table。
--   cb_number = sqlite source row identity (seed identity)
--   last_chemical_id = 最近一次 resolver 结果的运行记录, 非 identity authority
--   scheduler 每次处理 seed 必须重新走 resolver, 不得信 ledger 缓存
--   无 FK 到 chemistry.chemicals (canonical absorb 不得被 ingestion ledger 拖累)
--   不参与 can_merge / survivor / 不反向定义 chemicals

CREATE SCHEMA IF NOT EXISTS ingestion;

CREATE TABLE IF NOT EXISTS ingestion.chemicalbook_seed (
    cb_number       TEXT PRIMARY KEY,          -- sqlite compounds.cb_number (source identity)
    cas             TEXT NOT NULL,             -- 仅合法格式 CAS (loader 校验后写入)
    status          TEXT NOT NULL DEFAULT 'ACCEPTED'
                    CHECK (status IN ('ACCEPTED','RESOLVED_EXISTING','PENDING_NEW',
                                      'AMBIGUOUS','CONFLICT','ENQUEUED','ERROR')),
    last_chemical_id BIGINT,                   -- 运行记录; 使用前必须 canonicalize
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    enqueued_at     TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- scheduler keyset: (status, cb_number) 顺序取待处理 seed
CREATE INDEX IF NOT EXISTS chemicalbook_seed_status_cb_idx
    ON ingestion.chemicalbook_seed (status, cb_number);
-- 审计/分析口径: 按 CAS 找 seed (只读用途)
CREATE INDEX IF NOT EXISTS chemicalbook_seed_cas_idx
    ON ingestion.chemicalbook_seed (cas);
