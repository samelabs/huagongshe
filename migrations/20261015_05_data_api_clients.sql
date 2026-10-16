-- 对外数据服务的凭证与用量表。
-- 只新增对象(独立 schema data_api), 不触碰既有表; 回退方式为
-- DROP SCHEMA data_api CASCADE(无外键指向站内其他 schema)。

CREATE SCHEMA IF NOT EXISTS data_api;

-- 凭证: 由管理员发放, 令牌只存哈希(明文仅在发放时显示一次)。
CREATE TABLE IF NOT EXISTS data_api.clients (
    id              bigserial PRIMARY KEY,
    client_id       text NOT NULL UNIQUE,
    name            text NOT NULL,
    contact         text NOT NULL DEFAULT '',
    scopes          text[] NOT NULL,
    rate_per_minute integer NOT NULL DEFAULT 60,
    rate_per_day    integer NOT NULL DEFAULT 20000,
    enabled         boolean NOT NULL DEFAULT true,
    expires_at      timestamptz,
    created_by      bigint NOT NULL REFERENCES community.users(id),
    token_hash      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE data_api.clients IS
    '对外数据服务的接入凭证; 令牌明文不落库, 只存 sha256 哈希';

-- 每凭证每日调用量与错误量(管理页展示; 失败容忍, 不影响请求)。
CREATE TABLE IF NOT EXISTS data_api.usage_daily (
    client_id bigint NOT NULL REFERENCES data_api.clients(id) ON DELETE CASCADE,
    day       date NOT NULL,
    calls     bigint NOT NULL DEFAULT 0,
    errors    bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (client_id, day)
);
COMMENT ON TABLE data_api.usage_daily IS
    '对外数据服务按凭证计的每日调用量/错误量计数';
