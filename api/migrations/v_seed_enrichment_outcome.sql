-- ingestion.v_seed_enrichment_outcome (0907 consumption control-plane)
-- 纯 observability: 只读派生, 不参与 scheduler identity judgment,
-- 不宣称 last_chemical_id 是 canonical authority(治理冻结)。
-- recorded_chemical_id = ledger 运行记录;
-- current_chemical_id = redirect 表能一步映射到的 id(不重放 redirect 链,
-- 不复刻 canonicalize_id 机制 — 深链观察值可为 NULL, 见视图注释)。
CREATE OR REPLACE VIEW ingestion.v_seed_enrichment_outcome AS
SELECT
    s.cb_number,
    s.cas,
    s.status                        AS seed_status,
    s.last_chemical_id              AS recorded_chemical_id,
    COALESCE(r.canonical_chemical_id, s.last_chemical_id)
                                    AS current_chemical_id,
    (r.canonical_chemical_id IS NOT NULL) AS recorded_id_was_stale,
    cb.last_status                  AS cb_last_status,
    (cb.last_status = 'ok')         AS cb_ok,
    (cb.last_status = 'not_found')  AS cb_not_found,
    (c.mol IS NOT NULL)             AS has_mol,
    (c.inchikey IS NOT NULL)        AS has_inchikey,
    (c.pubchem_cid IS NOT NULL)     AS has_pubchem_cid,
    -- enriched = 该 seed 的 current chemical 已获得任一强结构证据
    (c.mol IS NOT NULL OR c.inchikey IS NOT NULL
     OR c.pubchem_cid IS NOT NULL OR cb.last_status = 'ok') AS enriched
FROM ingestion.chemicalbook_seed s
LEFT JOIN maintenance.chemical_identity_redirect r
       ON r.old_chemical_id = s.last_chemical_id
LEFT JOIN chemistry.chemical_cb cb
       ON cb.chemical_id = COALESCE(r.canonical_chemical_id,
                                    s.last_chemical_id)
      AND cb.locale = 'zh-CN'
LEFT JOIN chemistry.chemicals c
       ON c.id = COALESCE(r.canonical_chemical_id, s.last_chemical_id);
-- 注: redirect 深链(两跳以上)此处不追踪 — 该场景由 scheduler 的
-- canonicalize_id 在写路径处理, 视图只做一步观察。
