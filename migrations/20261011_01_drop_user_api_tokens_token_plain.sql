-- 2026-10-11 v1.7 收口（用户裁定，撤销 20260831 history 决策）:
-- AI Key 明文不再落库、不再回传。
-- token_plain 列删除即弃其数据; 列已不存在(新 baseline / 重复执行)时为 no-op ——
-- 本 migration 必须对「旧世界(有列)」与「新世界(无列)」都幂等, 因为
-- MigrationRunnerTests 等场景会在新 baseline 之上重放整条 forward 链。
-- 鉴权只依赖 token_hash(sha256), 不受影响 —— 存量 Key 继续有效,
-- 但无法再查看明文, 丢失只能新建。
-- 历史决策档案见 migrations/history/20260831_token_plain_column.sql(内容冻结)。

ALTER TABLE community.user_api_tokens DROP COLUMN IF EXISTS token_plain;
