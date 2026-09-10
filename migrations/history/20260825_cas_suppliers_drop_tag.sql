-- 供应商推广位字段清洗: tag(黄金产品/现货/大货/新品)为原站付费推广标识,
-- 解析层已停止产出, 存量已置 NULL, 此迁移去列收口。
ALTER TABLE chemistry.cas_suppliers DROP COLUMN IF EXISTS tag;
