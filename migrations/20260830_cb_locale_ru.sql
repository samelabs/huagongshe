-- 2026-08-30 CB链重构 Step 5: locale 规范对齐 IETF/BCP47, 补 ru(俄语, CPP _RU 后缀)。
-- 线上已执行同义 ALTER(应急), 本文件为准线记录。
ALTER TABLE chemistry.chemical_cb
    DROP CONSTRAINT chemical_cb_locale_check,
    ADD CONSTRAINT chemical_cb_locale_check
    CHECK (locale IN ('zh-CN','en','ja','de','ko','ru'));
