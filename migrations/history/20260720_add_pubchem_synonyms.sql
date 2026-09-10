BEGIN;

ALTER TABLE maintenance.pubchem_jobs
    DROP CONSTRAINT pubchem_jobs_sections_valid;

ALTER TABLE maintenance.pubchem_jobs
    ADD CONSTRAINT pubchem_jobs_sections_valid CHECK (
        cardinality(sections) BETWEEN 1 AND 9 AND
        sections <@ ARRAY[
            'computed','identifiers','synonyms','physical','safety','toxicity',
            'regulatory','pharmacology','uses'
        ]::text[]
    );

ALTER TABLE maintenance.pubchem_jobs OWNER TO huagongshe;

COMMIT;
