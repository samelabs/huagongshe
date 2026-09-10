-- cas-externals: ChemicalBook 中文条目/供应商 扩展表 + 任务队列 (批次2/3)
-- 机制镜像 pubchem_jobs/chemical_details(独立表,不混用),驱动链:
--   访问 -> ensure_externals() -> fresh 直出 | miss 同步拉(3s预算) | stale 出旧+入队
--   worker 双队列认领 cas_jobs + 周期自扫 expires_at 超期分批入队

-- 1) 条目表: 一行一化合物, not_found 也落行(行即负缓存)
CREATE TABLE IF NOT EXISTS chemistry.cas_externals (
    chemical_id  integer PRIMARY KEY REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
    cas_number   text NOT NULL,
    entry_cn     jsonb,
    last_status  text NOT NULL DEFAULT 'ok'
                 CHECK (last_status IN ('ok','not_found','error')),
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS cas_externals_cas_uidx
    ON chemistry.cas_externals (cas_number);
CREATE INDEX IF NOT EXISTS cas_externals_expiry_idx
    ON chemistry.cas_externals (expires_at)
    WHERE last_status = 'ok';

-- 2) 供应商表: 一行一(化合物×供应商), 刷新=整组替换
CREATE TABLE IF NOT EXISTS chemistry.cas_suppliers (
    chemical_id  integer NOT NULL REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
    ref          text NOT NULL,            -- CBSID sha256 前16hex(caslib.redact)
    name         text NOT NULL,
    tag          text,
    phone        text,
    email        text,
    website      text,
    purity       text,
    pack_price   text,
    remark       text,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chemical_id, ref)
);
CREATE INDEX IF NOT EXISTS cas_suppliers_cas_idx
    ON chemistry.cas_suppliers (chemical_id);

-- 3) 任务表: 镜像 pubchem_jobs 结构(列子集, cas 无 sections 概念)
CREATE TABLE IF NOT EXISTS maintenance.cas_jobs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chemical_id     integer REFERENCES chemistry.chemicals(id) ON DELETE SET NULL,
    cas_number      text NOT NULL,
    priority        smallint NOT NULL DEFAULT 50,
    status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','leased','retry','succeeded','failed','dead')),
    dedupe_key      text NOT NULL,
    request_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempt_count   smallint NOT NULL DEFAULT 0,
    max_attempts    smallint NOT NULL DEFAULT 3,
    not_before      timestamptz NOT NULL DEFAULT now(),
    lease_owner     text,
    lease_token_hash bytea,
    lease_expires_at timestamptz,
    heartbeat_at    timestamptz,
    result_summary  jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error_code text,
    last_error_detail text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz
);
-- 活跃窗口去重(同 pubchem_jobs_active_dedupe_uidx 模式)
CREATE UNIQUE INDEX IF NOT EXISTS cas_jobs_active_dedupe_uidx
    ON maintenance.cas_jobs (dedupe_key)
    WHERE status IN ('queued','leased','retry');
CREATE INDEX IF NOT EXISTS cas_jobs_claim_idx
    ON maintenance.cas_jobs (priority DESC, not_before, id)
    WHERE status IN ('queued','retry');
CREATE INDEX IF NOT EXISTS cas_jobs_lease_expiry_idx
    ON maintenance.cas_jobs (lease_expires_at, id)
    WHERE status = 'leased';
CREATE INDEX IF NOT EXISTS cas_jobs_completed_retention_idx
    ON maintenance.cas_jobs (completed_at, id)
    WHERE status IN ('succeeded','failed','dead') AND completed_at IS NOT NULL;

-- worker_clients.scopes 数组加 'cas' 值即可复用同一认证/租约协议,无需新表。
