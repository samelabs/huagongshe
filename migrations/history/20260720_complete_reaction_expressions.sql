BEGIN;

SET LOCAL statement_timeout = '0';
SET LOCAL lock_timeout = '10s';

ALTER TABLE ingest.reaction_rdkit_failures
  ALTER COLUMN reaction_smiles DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS reason text NOT NULL DEFAULT 'rdkit_parse_failure';

WITH expanded AS MATERIALIZED (
  SELECT rx.id AS reaction_id,
         rc.role,
         rc.chemical_id,
         repeated.n,
         c.smiles
  FROM chemistry.reactions rx
  JOIN chemistry.reaction_chemicals rc ON rc.reaction_id=rx.id
  JOIN chemistry.chemicals c ON c.id=rc.chemical_id
  CROSS JOIN LATERAL generate_series(1,rc.occurrence_count) repeated(n)
  WHERE rx.reaction IS NULL
), expressions AS MATERIALIZED (
  SELECT reaction_id,
         string_agg(smiles,'.' ORDER BY chemical_id,n)
           FILTER (WHERE role='REACTANT') AS reactants,
         string_agg(smiles,'.' ORDER BY role,chemical_id,n)
           FILTER (WHERE role NOT IN ('REACTANT','PRODUCT')) AS agents,
         string_agg(smiles,'.' ORDER BY chemical_id,n)
           FILTER (WHERE role='PRODUCT') AS products
  FROM expanded
  GROUP BY reaction_id
), complete AS MATERIALIZED (
  SELECT reaction_id,
         reactants || '>' || coalesce(agents,'') || '>' || products AS expression
  FROM expressions
  WHERE reactants IS NOT NULL AND products IS NOT NULL
), updated AS (
  UPDATE chemistry.reactions rx
  SET reaction_smiles=complete.expression,
      reaction=complete.expression::public.reaction,
      updated_at=now()
  FROM complete
  WHERE rx.id=complete.reaction_id AND rx.reaction IS NULL
  RETURNING rx.id
)
SELECT count(*) AS reconstructed_reactions FROM updated;

WITH roles AS (
  SELECT rx.id,
         bool_or(rc.role='REACTANT') AS has_reactant,
         bool_or(rc.role='PRODUCT') AS has_product
  FROM chemistry.reactions rx
  LEFT JOIN chemistry.reaction_chemicals rc ON rc.reaction_id=rx.id
  WHERE rx.reaction IS NULL
  GROUP BY rx.id
)
INSERT INTO ingest.reaction_rdkit_failures(
  reaction_id,reaction_smiles,attempted_at,reason
)
SELECT id,NULL,now(),
       CASE
         WHEN NOT coalesce(has_reactant,false) AND NOT coalesce(has_product,false)
           THEN 'missing_reactant_and_product'
         WHEN NOT coalesce(has_reactant,false) THEN 'missing_reactant'
         WHEN NOT coalesce(has_product,false) THEN 'missing_product'
         ELSE 'missing_source_expression'
       END
FROM roles
ON CONFLICT(reaction_id) DO UPDATE
SET reaction_smiles=excluded.reaction_smiles,
    attempted_at=excluded.attempted_at,
    reason=excluded.reason;

DO $$
DECLARE
  remaining bigint;
  audited bigint;
BEGIN
  SELECT count(*) INTO remaining
  FROM chemistry.reactions WHERE reaction IS NULL;
  SELECT count(*) INTO audited
  FROM ingest.reaction_rdkit_failures;
  IF remaining <> 121 OR audited <> remaining THEN
    RAISE EXCEPTION 'reaction residual validation failed: remaining=%, audited=%',
      remaining,audited;
  END IF;
  IF EXISTS (
    SELECT 1 FROM chemistry.reactions
    WHERE reaction_smiles IS NOT NULL AND reaction IS NULL
  ) THEN
    RAISE EXCEPTION 'a reaction SMILES exists without a materialized RDKit reaction';
  END IF;
END $$;

ANALYZE chemistry.reactions;
ANALYZE ingest.reaction_rdkit_failures;

COMMIT;
