BEGIN;

ALTER TABLE chemistry.chemical_details
    ADD COLUMN section_source_hashes jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE chemistry.chemical_details
    ADD CONSTRAINT chemical_details_section_hashes_object
    CHECK (jsonb_typeof(section_source_hashes) = 'object');

CREATE INDEX pubchem_jobs_completed_retention_idx
    ON maintenance.pubchem_jobs(completed_at, id)
    WHERE status IN ('succeeded', 'failed', 'dead') AND completed_at IS NOT NULL;

ALTER TABLE chemistry.chemical_details OWNER TO huagongshe;
ALTER TABLE maintenance.pubchem_jobs OWNER TO huagongshe;

COMMIT;
