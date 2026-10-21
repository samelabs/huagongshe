-- 笔记 slug 列默认值：任何不带 slug 的 INSERT（历史调用方/测试夹具）
-- 由数据库生成 7 位随机值兜底（md5 前缀 ⊂ 小写字母数字，满足格式约束）。
-- 应用层（services/notes.py）仍显式生成全字母表 slug。

ALTER TABLE community.notes
    ALTER COLUMN slug
    SET DEFAULT substr(md5(random()::text || clock_timestamp()::text), 1, 7);
