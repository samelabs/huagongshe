-- name_index: 名称检索字典(纯派生镜像, 无独立状态)
-- 来源: cb(entry_cn 名称/别名 + 供应商名) / pubchem(synonyms)
-- 检索: normalized 上的 trgm GIN + LIKE 子串
BEGIN;

CREATE TABLE IF NOT EXISTS chemistry.name_index (
    chemical_id integer NOT NULL REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
    name        text NOT NULL,
    lang        text NOT NULL CHECK (lang IN ('cn', 'en')),
    normalized  text NOT NULL,
    source      text NOT NULL CHECK (source IN ('cb', 'pubchem')),
    kind        text NOT NULL CHECK (kind IN ('name_cn', 'name_en', 'alias_cn', 'alias_en', 'supplier', 'synonym_en')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chemical_id, source, kind, normalized)
);

CREATE INDEX IF NOT EXISTS name_index_normalized_trgm_idx
    ON chemistry.name_index USING gin (normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS name_index_chemical_id_idx
    ON chemistry.name_index (chemical_id);

COMMENT ON TABLE chemistry.name_index IS
    '名称检索字典: CB 中文名/别名/供应商名 + PubChem synonyms 的派生镜像, 由摄入函数全量替换维护';

COMMIT;
