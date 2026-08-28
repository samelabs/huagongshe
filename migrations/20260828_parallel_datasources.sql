-- 20260828_parallel_datasources.sql — 数据源平行化四表定局
-- chemicals(+cb_number) / chemical_details→chemical_pubchem /
-- cas_externals→chemical_cb(locale) / cas_suppliers→chemical_supplier(locale)
-- cb_suppliers+cb_product_suppliers 并入 chemical_supplier 后 DROP
-- 前置: ~/ops/backup-20260828/cb_tables_data.sql 已备份(四表 data-only)

BEGIN;

-- ============ 1) 主表: cb_number 入 chemicals ============
ALTER TABLE chemistry.chemicals ADD COLUMN IF NOT EXISTS cb_number text;
UPDATE chemistry.chemicals c
SET cb_number = e.cb_number
FROM chemistry.cas_externals e
WHERE e.chemical_id = c.id AND e.cb_number IS NOT NULL AND c.cb_number IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS chemicals_cb_number_uidx
    ON chemistry.chemicals (cb_number) WHERE cb_number IS NOT NULL;

-- ============ 2) PubChem 扩展表改名 ============
ALTER TABLE chemistry.chemical_details RENAME TO chemical_pubchem;
ALTER INDEX chemistry.chemical_details_pkey RENAME TO chemical_pubchem_pkey;
ALTER INDEX chemistry.chemical_details_expiry_idx RENAME TO chemical_pubchem_expiry_idx;

-- ============ 3) cas_externals → chemical_cb (locale 多语言) ============
ALTER TABLE chemistry.cas_externals RENAME TO chemical_cb;
ALTER INDEX chemistry.cas_externals_pkey RENAME TO chemical_cb_pkey;
ALTER INDEX chemistry.cas_externals_expiry_idx RENAME TO chemical_cb_expiry_idx;
ALTER TABLE chemistry.chemical_cb ADD COLUMN locale text NOT NULL DEFAULT 'zh-CN';
ALTER TABLE chemistry.chemical_cb DROP CONSTRAINT chemical_cb_pkey;
ALTER TABLE chemistry.chemical_cb
    ADD CONSTRAINT chemical_cb_locale_check CHECK (locale IN ('zh-CN','en','ja','de','ko'));
ALTER TABLE chemistry.chemical_cb
    ADD PRIMARY KEY (chemical_id, locale);
ALTER TABLE chemistry.chemical_cb RENAME COLUMN entry_cn TO entry;
-- cb_number 已上移主表, 本表删列(join 可得, 零冗余)
ALTER TABLE chemistry.chemical_cb DROP COLUMN cb_number;

-- ============ 4) cas_suppliers → chemical_supplier (locale=供应商国家) ============
ALTER TABLE chemistry.cas_suppliers RENAME TO chemical_supplier;
ALTER INDEX chemistry.cas_suppliers_pkey RENAME TO chemical_supplier_pkey;
ALTER INDEX chemistry.cas_suppliers_cas_idx RENAME TO chemical_supplier_chemical_idx;
ALTER TABLE chemistry.chemical_supplier ADD COLUMN locale text;
CREATE INDEX IF NOT EXISTS chemical_supplier_cbsid_idx
    ON chemistry.chemical_supplier (cbsid) WHERE cbsid IS NOT NULL;

-- ============ 5) cb 两表并入 chemical_supplier ============
-- 关联行: cb_product_suppliers(cas,cbsid) -> chemical_supplier(chemical_id, ref=cbsid派生)
-- 重叠行(同chemical同cbsid已存在快照层) coalesce 补 locale(nationality)+website;
-- 新行 INSERT(ref 由 supplier_ref(cbsid) 同算法 sha256 前16hex 派生)。
INSERT INTO chemistry.chemical_supplier
    (chemical_id, ref, cbsid, name, phone, email, website, purity, pack_price, remark, locale)
SELECT e.chemical_id,
       encode(sha256(('hgs-cas-supplier:' || p.cbsid)::bytea), 'hex') ,
       p.cbsid,
       s.name, s.phone, s.email, s.website,
       p.purity, p.pack_price, p.remark,
       s.nationality
FROM chemistry.cb_product_suppliers p
JOIN chemistry.cb_suppliers s ON s.cbsid = p.cbsid
JOIN chemistry.chemical_cb e ON e.cas_number = p.cas_number AND e.locale = 'zh-CN'
ON CONFLICT (chemical_id, ref) DO UPDATE SET
    locale = coalesce(chemistry.chemical_supplier.locale, excluded.locale),
    website = coalesce(chemistry.chemical_supplier.website, excluded.website),
    cbsid = coalesce(chemistry.chemical_supplier.cbsid, excluded.cbsid);

-- 对账后 DROP 两表(对账在事务外由执行脚本核验, 不满足即整体 ROLLBACK)
DROP TABLE chemistry.cb_product_suppliers;
DROP TABLE chemistry.cb_suppliers;

COMMIT;
