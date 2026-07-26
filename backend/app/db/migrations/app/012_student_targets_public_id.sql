-- `student_targets` (002_profile.sql) was created without a `public_id`
-- column, unlike every sibling table in this schema (programmes,
-- institutions, documents, scholarships, ...). docs/api_contract.md
-- section 1 is explicit that every id crossing the wire is the public_id
-- ULID, never the integer primary key, and app/repositories/target_repo.py
-- has always selected `st.public_id` and inserted one on create -- it was
-- simply never given a column to live in.
--
-- Found by running GET/POST/DELETE /me/targets end to end while building
-- the router layer: every read failed with "no such column: st.public_id".
-- No backfill statement is needed: this migration only ever runs against a
-- database created by this same migration set, so `student_targets` is
-- always empty at this point (schema migrations run before any request,
-- including the demo-account seed, can insert a row), and
-- TargetRepo.create_target already supplies a public_id on every insert
-- going forward.
ALTER TABLE student_targets ADD COLUMN public_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_targets_public_id ON student_targets(public_id);
