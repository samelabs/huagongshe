-- DOI names are case-insensitive. Both user-maintained and ORD provenance
-- lookups must use expression indexes instead of scanning 2.4M reactions.
CREATE INDEX CONCURRENTLY IF NOT EXISTS reactions_doi_lower_idx
  ON chemistry.reactions(lower(doi), id)
  WHERE doi IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS reaction_provenance_doi_lower_idx
  ON ord.reaction_provenance(lower(doi), reaction_id, id)
  WHERE doi IS NOT NULL;
