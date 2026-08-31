-- 2026-08-31 审计 M4 补录: chemical_supplier_profile / chemical_supplier_listing
-- 两表 2026-08-2x 由 cas_externals.py 侧直接建在生产库(profile 2,626 行 / listing 16,848 行),
-- migrations/ 零记录, 灾备重建即断 CB 链写入。本文件按 live DDL 精确复刻(information_schema
-- 抓取的列定义/约束/索引), 线上已存在同构表, 执行时靠 IF NOT EXISTS 幂等跳过。

CREATE TABLE IF NOT EXISTS chemistry.chemical_supplier_profile (
    cbsid      text PRIMARY KEY,              -- 原站供应商ID(身份键, 仅DB)
    name       text,
    ref        text,
    phone      text,
    email      text,
    website    text,
    locale     text,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + '180 days'::interval)
);

CREATE TABLE IF NOT EXISTS chemistry.chemical_supplier_listing (
    chemical_id integer NOT NULL,
    cbsid       text NOT NULL,
    purity      text,
    pack_price  text,
    remark      text,
    fetched_at  timestamptz NOT NULL,
    PRIMARY KEY (chemical_id, cbsid)
);

ALTER TABLE chemistry.chemical_supplier_listing
    DROP CONSTRAINT IF EXISTS chemical_supplier_listing_cbsid_fkey;
ALTER TABLE chemistry.chemical_supplier_listing
    ADD CONSTRAINT chemical_supplier_listing_cbsid_fkey
    FOREIGN KEY (cbsid) REFERENCES chemistry.chemical_supplier_profile(cbsid) ON DELETE CASCADE;

ALTER TABLE chemistry.chemical_supplier_listing
    DROP CONSTRAINT IF EXISTS chemical_supplier_listing_chemical_id_fkey;
ALTER TABLE chemistry.chemical_supplier_listing
    ADD CONSTRAINT chemical_supplier_listing_chemical_id_fkey
    FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS chemical_supplier_listing_cbsid_idx
    ON chemistry.chemical_supplier_listing (cbsid);
