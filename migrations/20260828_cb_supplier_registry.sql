-- CB 供应商主档 + 品目关联 (2026-08-28 定案)
-- 设计: cbsid 为主键的供应商实体表(跨品目一份) + cas↔cbsid 关联表(带品级字段)。
-- cas_suppliers 保留为详情页快照读层(不动消费端), 数据由同事务双写。

CREATE TABLE IF NOT EXISTS chemistry.cb_suppliers (
    cbsid       text PRIMARY KEY,              -- 原站供应商ID(身份键, 仅DB)
    name        text NOT NULL,
    nationality text,                          -- 国籍(GW国际供应商: 德国/日本/美洲…; GN国内=中国)
    phone       text,
    email       text,
    website     text,
    cb_index    integer,                       -- CB指数(供应商活跃度, GW页)
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chemistry.cb_product_suppliers (
    cas_number  text NOT NULL,
    cbsid       text NOT NULL,
    source      text NOT NULL CHECK (source IN ('gn','gw')),  -- GN国内列表 / GW国际列表
    product_name_en text,                      -- 品目英文名(GW页: 英文名称)
    purity      text,
    pack_price  text,
    remark      text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cas_number, cbsid)
);

CREATE INDEX IF NOT EXISTS cb_product_suppliers_cbsid_idx
    ON chemistry.cb_product_suppliers (cbsid);

COMMENT ON TABLE chemistry.cb_suppliers IS 'CB供应商主档: cbsid身份键, 跨品目一份; 原站标识仅DB不进API';
COMMENT ON TABLE chemistry.cb_product_suppliers IS 'CAS↔供应商关联表: 品级字段随品目, 主档信息随供应商';
