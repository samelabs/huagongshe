-- I-087: name_index.lang 放宽到全部 CB locale。
-- 现有值只有 'cn'/'en'(zh-CN 历史代码沿用 'cn', 见 services/name_index.py 说明),
-- 新增 ja/ko/de。本文件只做 DROP + ADD ... NOT VALID: 两步都在瞬时完成的
-- ACCESS EXCLUSIVE 锁内(DROP/ADD 元数据操作, 不扫表), 事务即刻提交,
-- 不会阻塞名称搜索与 worker 写入。
-- VALIDATE 单独放在 20261015_04: 校验需要全表扫描, 锁级别与耗时见该文件头。

ALTER TABLE chemistry.name_index DROP CONSTRAINT name_index_lang_check;

ALTER TABLE chemistry.name_index
    ADD CONSTRAINT name_index_lang_check
    CHECK (lang = ANY (ARRAY['cn'::text, 'en'::text, 'ja'::text, 'ko'::text, 'de'::text]))
    NOT VALID;
