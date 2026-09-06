-- 0906 身份裁定机制规范 3.6: merge 基础设施 (批量 absorb 前置阻断项)
-- 幂等: 已存在则跳过 (CREATE TABLE IF NOT EXISTS)

-- 3.6.2 合并审计 — 每次 absorb 的凭证与两侧 before snapshot
CREATE TABLE IF NOT EXISTS maintenance.identity_merge_log (
    merge_id            bigserial PRIMARY KEY,
    source_id           bigint  NOT NULL,            -- 被吸收行(已删除)
    target_id           bigint  NOT NULL,            -- 保留行(survivor)
    reason              text    NOT NULL,
    evidence            jsonb   NOT NULL DEFAULT '{}',
    source_keys_before  jsonb   NOT NULL DEFAULT '{}',
    target_keys_before  jsonb   NOT NULL DEFAULT '{}',
    trigger             text,
    merged_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_identity_merge_log_source
    ON maintenance.identity_merge_log (source_id);
CREATE INDEX IF NOT EXISTS ix_identity_merge_log_target
    ON maintenance.identity_merge_log (target_id);

COMMENT ON TABLE  maintenance.identity_merge_log IS
    '身份合并审计: absorb 前落表, 含两侧 before snapshot(JSONB), 回滚/复查依据';
COMMENT ON COLUMN maintenance.identity_merge_log.source_id IS
    '被吸收并删除的行 id (经 redirect 仍可追溯)';

-- 3.6.3 运行时重定向 — DELETE 主行可以, 身份历史不删
-- 异步 worker 持旧 chemical_id 执行时经 canonicalize_id(old) 解析, 不报错不重建
CREATE TABLE IF NOT EXISTS maintenance.chemical_identity_redirect (
    old_chemical_id     bigint  NOT NULL,
    canonical_chemical_id bigint NOT NULL,
    merge_log_id        bigint  REFERENCES maintenance.identity_merge_log (merge_id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (old_chemical_id)
);

COMMENT ON TABLE maintenance.chemical_identity_redirect IS
    '旧 chemical_id → canonical 映射; canonicalize_id 查询, merge_log 管审计本表管运行时兼容';
