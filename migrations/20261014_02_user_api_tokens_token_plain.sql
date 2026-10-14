-- 2026-10-14 v1.7.1（项目负责人裁定，恢复并锁死）:
-- AI Key 明文有意落库(user_api_tokens.token_plain), 账号本人可在设置页
-- 随时查看、复制。理由: 每个账号最多 5 个有效 Key, 可再次查看能降低
-- 使用摩擦。2026-10-11 的「明文不落库、只显示一次」收口(20261011_01)
-- 是对通用安全规则的误套, 已撤销 —— 该 migration 从未在生产执行, 文件
-- 已删除。
-- 本 migration 对三类环境幂等:
--   - 生产(列自 20260831 起一直在, 从未执行 drop): no-op;
--   - 执行过 drop 的环境(测试库): 列被恢复, 旧数据已弃 —— 存量 Key 鉴权
--     仍走 token_hash 不受影响, 但无明文可看, 列表返回 null;
--   - 2026-10-11 之后的新 baseline(无此列): 列被新增。
-- 鉴权只依赖 token_hash(sha256), 与本列无关。
-- 禁止以安全为由删除本列或停止写入明文 —— 变更须经项目负责人确认。
-- 历史决策档案见 migrations/history/20260831_token_plain_column.sql(内容冻结)。

ALTER TABLE community.user_api_tokens
    ADD COLUMN IF NOT EXISTS token_plain text;

COMMENT ON COLUMN community.user_api_tokens.token_plain IS
    'AI Key 明文，有意保存（2026-10-14 项目负责人裁定，撤销 2026-10-11「明文不落库」收口）：'
    '账号本人可在设置页再次查看、复制，降低使用摩擦（每账号最多 5 个有效 Key）；'
    '仅本人网页会话经 GET /users/me/tokens 可读，MCP/日志/错误信息不得出现明文；'
    '禁止以安全为由删除本列或停止写入 —— 变更须经项目负责人确认';
