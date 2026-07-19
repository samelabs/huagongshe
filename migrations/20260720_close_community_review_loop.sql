BEGIN;

ALTER TABLE community.chemical_submissions
  ADD COLUMN IF NOT EXISTS submitted_name text,
  ADD COLUMN IF NOT EXISTS reviewer_id bigint REFERENCES community.users(id),
  ADD COLUMN IF NOT EXISTS review_note text,
  ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;

ALTER TABLE community.reaction_submissions
  ADD COLUMN IF NOT EXISTS procedure_details text,
  ADD COLUMN IF NOT EXISTS conditions_detail text,
  ADD COLUMN IF NOT EXISTS temperature_value double precision,
  ADD COLUMN IF NOT EXISTS temperature_unit text,
  ADD COLUMN IF NOT EXISTS duration_value double precision,
  ADD COLUMN IF NOT EXISTS duration_unit text,
  ADD COLUMN IF NOT EXISTS ph double precision,
  ADD COLUMN IF NOT EXISTS atmosphere text,
  ADD COLUMN IF NOT EXISTS pressure_value double precision,
  ADD COLUMN IF NOT EXISTS pressure_unit text,
  ADD COLUMN IF NOT EXISTS safety_notes text,
  ADD COLUMN IF NOT EXISTS doi text,
  ADD COLUMN IF NOT EXISTS patent text,
  ADD COLUMN IF NOT EXISTS source_url text,
  ADD COLUMN IF NOT EXISTS reviewer_id bigint REFERENCES community.users(id),
  ADD COLUMN IF NOT EXISTS review_note text,
  ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;

CREATE TABLE IF NOT EXISTS community.reaction_submission_participants (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  submission_id bigint NOT NULL
    REFERENCES community.reaction_submissions(id) ON DELETE CASCADE,
  position integer NOT NULL CHECK (position >= 0),
  role text NOT NULL CHECK (
    role IN ('REACTANT', 'REAGENT', 'CATALYST', 'SOLVENT', 'PRODUCT')
  ),
  submitted_smiles text NOT NULL,
  canonical_smiles text NOT NULL,
  chemical_id integer REFERENCES chemistry.chemicals(id),
  yield_percent double precision CHECK (
    yield_percent IS NULL OR (yield_percent >= 0 AND yield_percent <= 100)
  ),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, position)
);

CREATE INDEX IF NOT EXISTS reaction_submission_participants_submission_idx
  ON community.reaction_submission_participants(submission_id, position);
CREATE INDEX IF NOT EXISTS reaction_submission_participants_chemical_idx
  ON community.reaction_submission_participants(chemical_id)
  WHERE chemical_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chemical_submissions_reviewer_idx
  ON community.chemical_submissions(reviewer_id, reviewed_at DESC)
  WHERE reviewer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS reaction_submissions_reviewer_idx
  ON community.reaction_submissions(reviewer_id, reviewed_at DESC)
  WHERE reviewer_id IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'community.reaction_submissions'::regclass
      AND conname = 'reaction_submissions_temperature_unit_check'
  ) THEN
    ALTER TABLE community.reaction_submissions ADD CONSTRAINT reaction_submissions_temperature_unit_check
      CHECK (temperature_unit IS NULL OR temperature_unit IN ('CELSIUS', 'KELVIN'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'community.reaction_submissions'::regclass
      AND conname = 'reaction_submissions_duration_unit_check'
  ) THEN
    ALTER TABLE community.reaction_submissions ADD CONSTRAINT reaction_submissions_duration_unit_check
      CHECK (duration_unit IS NULL OR duration_unit IN ('MINUTE', 'HOUR', 'DAY'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'community.reaction_submissions'::regclass
      AND conname = 'reaction_submissions_ph_check'
  ) THEN
    ALTER TABLE community.reaction_submissions ADD CONSTRAINT reaction_submissions_ph_check
      CHECK (ph IS NULL OR (ph >= 0 AND ph <= 14));
  END IF;
END $$;

COMMIT;
