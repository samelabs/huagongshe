BEGIN;

UPDATE ingest.chemicals_import_meta
SET source_path = 'CID-SMILES.gz',
    identifiers_source_path = 'CID-Identifiers.tsv.gz'
WHERE source_path = '/var/www/ord-samelabs/CID-SMILES.gz'
   OR identifiers_source_path = '/var/www/ord-samelabs/CID-Identifiers.tsv.gz';

UPDATE ingest.dsstox_import_meta
SET source_path = '/var/lib/huagongshe/archive/20260720/import-source/DSSToxCCDdump.csv'
WHERE source_path = '/var/www/ord-samelabs/DSSToxCCDdump.csv';

COMMIT;
