-- OAuth Client ID Metadata Document (CIMD) 支持所需列。
-- 只加列、加注释; 不改不删已有数据。已有行 source_type 落默认值 'registered'。

ALTER TABLE community.oauth_clients
    ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'registered';
ALTER TABLE community.oauth_clients
    ADD COLUMN IF NOT EXISTS metadata_fetched_at timestamptz;
ALTER TABLE community.oauth_clients
    ADD COLUMN IF NOT EXISTS metadata_cache_until timestamptz;
ALTER TABLE community.oauth_clients
    ADD COLUMN IF NOT EXISTS client_uri text;
ALTER TABLE community.oauth_clients
    ADD COLUMN IF NOT EXISTS logo_uri text;

-- 加列默认值会把既有 DCR 行(client_id 形如 hgo_client_…)标成 'registered',
-- 与列注释不符: 统一改标 'dcr'(动态注册)。left() 前缀等值比较避免 LIKE
-- 通配符歧义。生产影响行数约 119(PM 口径), 不改动其余数据。
UPDATE community.oauth_clients
SET source_type = 'dcr'
WHERE left(client_id, 11) = 'hgo_client_'
  AND source_type = 'registered';

COMMENT ON COLUMN community.oauth_clients.source_type IS
    'client 来源: registered=预登记, dcr=动态注册(/oauth/register, 含历史 hgo_client_ 行), cimd=Client ID Metadata Document 拉取缓存(client_id 即 https URL)';
COMMENT ON COLUMN community.oauth_clients.metadata_fetched_at IS
    'CIMD: 最近一次成功拉取文档的时间; 其余来源为 NULL';
COMMENT ON COLUMN community.oauth_clients.metadata_cache_until IS
    'CIMD: 缓存有效期(由响应 Cache-Control max-age 夹在 5 分钟~24 小时得出); /authorize 超过该时间会重新拉取';
COMMENT ON COLUMN community.oauth_clients.client_uri IS
    'CIMD: 文档自报的 client_uri(已校验为 https); 仅保存暂不展示';
COMMENT ON COLUMN community.oauth_clients.logo_uri IS
    'CIMD: 文档自报的 logo_uri(已校验为 https); 仅保存暂不展示';
