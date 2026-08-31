-- 2026-08-31 Token 机制收口(用户裁定):
-- 1) 撤销=物理删除(不再留存 revoked 行)
-- 2) 支持"回头复制"明文(智谱/Gemini 同款体验): 加 token_plain 列。
--    个人查询工具口径, token_hash 保留作认证索引(明文列非认证路径)。
-- 存量行 token_plain 为 NULL(旧 token 仅前缀可见, 新建/删除重建即可)。

ALTER TABLE community.user_api_tokens
    ADD COLUMN IF NOT EXISTS token_plain text;
