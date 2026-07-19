BEGIN;

CREATE SCHEMA IF NOT EXISTS chemistry AUTHORIZATION huagongshe;
CREATE SCHEMA IF NOT EXISTS ingest AUTHORIZATION huagongshe;

ALTER TABLE pubchem.chemicals SET SCHEMA chemistry;
ALTER TABLE public.reactions SET SCHEMA chemistry;
ALTER TABLE public.reaction_chemicals SET SCHEMA chemistry;

ALTER TABLE public.occurrence_chemical_migration_meta SET SCHEMA ingest;
ALTER TABLE public.reaction_rdkit_failures SET SCHEMA ingest;
ALTER TABLE public.reaction_rdkit_migration_meta SET SCHEMA ingest;
ALTER TABLE public.reactions_migration_meta SET SCHEMA ingest;

ALTER TABLE pubchem.chemicals_import_meta SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_chemical_matches SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_import_meta SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_reconcile_meta SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_residual_cas_classification SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_residual_exact_candidates SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_residual_exact_safe SET SCHEMA ingest;
ALTER TABLE pubchem.dsstox_residual_stage SET SCHEMA ingest;
ALTER TABLE pubchem.rdkit_mol_absorption_meta SET SCHEMA ingest;
ALTER TABLE pubchem.rdkit_mol_chemical_map SET SCHEMA ingest;
ALTER TABLE pubchem.rdkit_mol_migration_meta SET SCHEMA ingest;
ALTER TABLE pubchem.rdkit_mol_payload_meta SET SCHEMA ingest;
ALTER TABLE pubchem.rdkit_mol_version_meta SET SCHEMA ingest;

ALTER TABLE ord.legacy_reaction_map RENAME TO reaction_map;

DROP SCHEMA pubchem RESTRICT;

COMMENT ON SCHEMA chemistry IS '化工社自主维护的化合物与反应核心数据';
COMMENT ON SCHEMA ingest IS '一次性导入、迁移和质量审计数据，不供线上业务直接查询';
COMMENT ON SCHEMA ord IS 'ORD 原始反应事实和来源上下文';
COMMENT ON SCHEMA community IS '用户、会话、提交与反应求助工作流';

COMMIT;
