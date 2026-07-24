-- Fix: pubchem_cid point lookups time out on the 124M-row BRIN index.
-- BRIN is designed for naturally ordered, range-scanned data (e.g. time-series).
-- PubChem CIDs are densely and unpredictably distributed across the heap;
-- a single-value lookup rechecks up to 730K rows via the BRIN range map.
-- This makes pure-digit queries (c.id = N OR c.pubchem_cid = N) exceed the
-- 5-second statement_timeout, returning 503 to the user.
--
-- A btree index gives O(log N) point lookups. Estimated size ~600-900 MB
-- on 124M integer rows, well within the server's disk budget.
--
-- Keep the BRIN for analytical/batch scans; the btree serves user-facing
-- point queries.

CREATE INDEX CONCURRENTLY IF NOT EXISTS chemicals_pubchem_cid_btree_idx
  ON chemistry.chemicals (pubchem_cid)
  WHERE pubchem_cid IS NOT NULL;

ANALYZE chemistry.chemicals (pubchem_cid);
