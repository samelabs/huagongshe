# 2026-07-19 data migration archive

This directory preserves one-time migration and audit artifacts that were
originally created in the unrelated `samelabs` working tree.

They document the historical PubChem/DSSTox/RDKit/ORD migration and may be
useful for auditing or recovery. They are **not current deployment scripts**:
several files reference retired schemas, compatibility objects, and table
layouts. Do not run them against a live database without reviewing them
against the current migrations and taking a verified backup.

- `chemicals/`: historical chemical import, reconciliation, indexing, and
  RDKit cutover utilities.
- `reactions/`: historical ORD occurrence and reaction materialization
  utilities.
- `cleanup_manifest_20260719.md`: the corresponding server cleanup audit.

The current database contract is defined by the SQL files in `migrations/`.
