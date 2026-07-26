-- Vault upload: why an extraction failed, in both languages.
--
-- documents.status already has a 'failed' state (migration 006), but there was
-- nowhere to record *why*, so a student whose scanned PDF could not be
-- rasterised saw a card that said "failed" and nothing else. Prohori's audit
-- findings are not the right home for this: they describe what a document
-- says, not that the vault could not read it at all.
--
-- Both columns are nullable and only set on the failure path, so every
-- existing row stays valid without a backfill.

ALTER TABLE documents ADD COLUMN failure_reason_en TEXT;
ALTER TABLE documents ADD COLUMN failure_reason_bn TEXT;
