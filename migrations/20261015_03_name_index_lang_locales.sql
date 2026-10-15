-- I-087: name_index.lang 放宽到全部 CB locale。
-- 现有值只有 'cn'/'en'(zh-CN 历史代码沿用 'cn', 见 services/name_index.py 说明),
-- 新增 ja/ko/de。NOT VALID + VALIDATE 两步: 加约束不扫全表(短 ACCESS EXCLUSIVE),
-- 校验阶段锁级别低(SHARE UPDATE EXCLUSIVE)不阻塞写入。1820 万行现有值全部
-- 满足新约束, VALIDATE 必然通过。

ALTER TABLE chemistry.name_index DROP CONSTRAINT name_index_lang_check;

ALTER TABLE chemistry.name_index
    ADD CONSTRAINT name_index_lang_check
    CHECK (lang = ANY (ARRAY['cn'::text, 'en'::text, 'ja'::text, 'ko'::text, 'de'::text]))
    NOT VALID;

ALTER TABLE chemistry.name_index VALIDATE CONSTRAINT name_index_lang_check;
