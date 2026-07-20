BEGIN;

CREATE SCHEMA IF NOT EXISTS maintenance;

CREATE TABLE chemistry.chemical_details (
    chemical_id integer PRIMARY KEY
        REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
    record_title text,
    record_description text,
    xlogp double precision,
    topological_polar_surface_area double precision,
    complexity double precision,
    hbond_donor_count integer,
    hbond_acceptor_count integer,
    rotatable_bond_count integer,
    heavy_atom_count integer,
    formal_charge integer,
    computed_properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    physical_properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    ghs_classification jsonb NOT NULL DEFAULT '{}'::jsonb,
    hazards jsonb NOT NULL DEFAULT '{}'::jsonb,
    safety_measures jsonb NOT NULL DEFAULT '{}'::jsonb,
    toxicity jsonb NOT NULL DEFAULT '{}'::jsonb,
    regulatory jsonb NOT NULL DEFAULT '{}'::jsonb,
    pharmacology jsonb NOT NULL DEFAULT '{}'::jsonb,
    uses_and_manufacturing jsonb NOT NULL DEFAULT '{}'::jsonb,
    identifier_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_references jsonb NOT NULL DEFAULT '{}'::jsonb,
    fetched_sections text[] NOT NULL DEFAULT ARRAY[]::text[],
    section_fetched_at jsonb NOT NULL DEFAULT '{}'::jsonb,
    pubchem_created_on date,
    pubchem_modified_on date,
    source_hash text,
    schema_version smallint NOT NULL DEFAULT 1,
    fetched_at timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT chemical_details_nonnegative_counts CHECK (
        (hbond_donor_count IS NULL OR hbond_donor_count >= 0) AND
        (hbond_acceptor_count IS NULL OR hbond_acceptor_count >= 0) AND
        (rotatable_bond_count IS NULL OR rotatable_bond_count >= 0) AND
        (heavy_atom_count IS NULL OR heavy_atom_count >= 0)
    ),
    CONSTRAINT chemical_details_json_objects CHECK (
        jsonb_typeof(computed_properties) = 'object' AND
        jsonb_typeof(physical_properties) = 'object' AND
        jsonb_typeof(ghs_classification) = 'object' AND
        jsonb_typeof(hazards) = 'object' AND
        jsonb_typeof(safety_measures) = 'object' AND
        jsonb_typeof(toxicity) = 'object' AND
        jsonb_typeof(regulatory) = 'object' AND
        jsonb_typeof(pharmacology) = 'object' AND
        jsonb_typeof(uses_and_manufacturing) = 'object' AND
        jsonb_typeof(identifier_evidence) = 'object' AND
        jsonb_typeof(source_references) = 'object' AND
        jsonb_typeof(section_fetched_at) = 'object'
    )
);

CREATE INDEX chemical_details_expiry_idx
    ON chemistry.chemical_details(expires_at, chemical_id)
    WHERE expires_at IS NOT NULL;

CREATE TABLE maintenance.worker_clients (
    worker_id text PRIMARY KEY,
    display_name text NOT NULL,
    token_hash bytea NOT NULL UNIQUE,
    token_prefix text NOT NULL,
    scopes text[] NOT NULL DEFAULT ARRAY['pubchem']::text[],
    enabled boolean NOT NULL DEFAULT true,
    max_lease_jobs smallint NOT NULL DEFAULT 4 CHECK (max_lease_jobs BETWEEN 1 AND 20),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    last_seen_at timestamp with time zone,
    disabled_at timestamp with time zone,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT worker_clients_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE maintenance.pubchem_jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chemical_id integer REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
    query_kind text NOT NULL CHECK (
        query_kind IN ('cid', 'cas', 'smiles', 'inchikey')
    ),
    query_value text NOT NULL CHECK (length(query_value) BETWEEN 1 AND 4000),
    sections text[] NOT NULL DEFAULT ARRAY['computed','identifiers']::text[],
    priority smallint NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'leased', 'retry', 'succeeded', 'failed', 'dead')
    ),
    dedupe_key text NOT NULL,
    requested_by_user_id bigint REFERENCES community.users(id) ON DELETE SET NULL,
    request_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempt_count smallint NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts smallint NOT NULL DEFAULT 6 CHECK (max_attempts BETWEEN 1 AND 20),
    not_before timestamp with time zone NOT NULL DEFAULT now(),
    lease_owner text REFERENCES maintenance.worker_clients(worker_id) ON DELETE SET NULL,
    lease_token_hash bytea,
    lease_expires_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    resolved_pubchem_cid integer,
    result_hash text,
    result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error_code text,
    last_error_detail text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    completed_at timestamp with time zone,
    CONSTRAINT pubchem_jobs_context_object CHECK (
        jsonb_typeof(request_context) = 'object' AND
        jsonb_typeof(result_summary) = 'object'
    ),
    CONSTRAINT pubchem_jobs_sections_valid CHECK (
        cardinality(sections) BETWEEN 1 AND 8 AND
        sections <@ ARRAY[
            'computed','identifiers','physical','safety','toxicity',
            'regulatory','pharmacology','uses'
        ]::text[]
    ),
    CONSTRAINT pubchem_jobs_lease_shape CHECK (
        (status <> 'leased') OR
        (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX pubchem_jobs_active_dedupe_uidx
    ON maintenance.pubchem_jobs(dedupe_key)
    WHERE status IN ('queued', 'leased', 'retry');

CREATE INDEX pubchem_jobs_claim_idx
    ON maintenance.pubchem_jobs(priority DESC, not_before, id)
    WHERE status IN ('queued', 'retry');

CREATE INDEX pubchem_jobs_lease_expiry_idx
    ON maintenance.pubchem_jobs(lease_expires_at, id)
    WHERE status = 'leased';

CREATE INDEX pubchem_jobs_chemical_idx
    ON maintenance.pubchem_jobs(chemical_id, created_at DESC)
    WHERE chemical_id IS NOT NULL;

CREATE TABLE maintenance.pubchem_job_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id bigint NOT NULL REFERENCES maintenance.pubchem_jobs(id) ON DELETE CASCADE,
    worker_id text REFERENCES maintenance.worker_clients(worker_id) ON DELETE SET NULL,
    event_type text NOT NULL CHECK (
        event_type IN ('queued', 'leased', 'heartbeat', 'succeeded', 'retry', 'failed', 'dead')
    ),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT pubchem_job_events_details_object CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX pubchem_job_events_job_idx
    ON maintenance.pubchem_job_events(job_id, created_at);

ALTER SCHEMA maintenance OWNER TO huagongshe;
ALTER TABLE chemistry.chemical_details OWNER TO huagongshe;
ALTER TABLE maintenance.worker_clients OWNER TO huagongshe;
ALTER TABLE maintenance.pubchem_jobs OWNER TO huagongshe;
ALTER TABLE maintenance.pubchem_job_events OWNER TO huagongshe;

COMMIT;
