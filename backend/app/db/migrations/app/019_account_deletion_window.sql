-- A 30-day window between asking for deletion and the data being gone.
--
-- Deletion was immediate and irreversible. A student who mistyped, who panicked
-- about a passport scan being online, or whose account was accessed by someone
-- else had no way back: the row was gone, the vault keys with it, and the uploaded
-- documents were unrecoverable. For a product whose users are keeping visa
-- paperwork in it, that is the wrong default in both directions, because it also
-- means a compromised session can destroy a student's file permanently.
--
-- The window fixes both. The request takes effect immediately as far as the
-- student is concerned, the account can be recovered by the account holder for 30
-- days, and after that a nightly job performs exactly the hard delete that used to
-- happen inline (app/workers/retention.py, purge_due_accounts).
--
-- The state is two nullable timestamps rather than a new `status` value. SQLite
-- cannot alter the CHECK constraint on `users.status` inside the transaction each
-- migration runs in, and the table has foreign keys from most of app.db, so
-- rebuilding it would be a large change to express a boolean. `deletion_requested_at
-- IS NOT NULL` is the state; nothing else needs to know.
ALTER TABLE users ADD COLUMN deletion_requested_at TEXT;

-- Stored rather than computed from requested_at at read time, so that the promise
-- made to the student is the promise the purge job reads. If the retention period
-- is ever shortened, an account already in the window keeps the date it was told.
ALTER TABLE users ADD COLUMN deletion_scheduled_for TEXT;

-- The purge job's only query. Partial, because the overwhelming majority of rows
-- have NULL here and there is no reason to index them.
CREATE INDEX IF NOT EXISTS idx_users_deletion_due
  ON users(deletion_scheduled_for) WHERE deletion_scheduled_for IS NOT NULL;

-- Login stays possible during the window, on purpose.
--
-- The alternative, locking the account out at request time, is what makes a grace
-- period useless: a student who changes their mind cannot sign in to say so, and
-- the only route back is a support request to a service with no support staff. The
-- session is therefore still valid, and every authenticated response carries the
-- scheduled date so the interface can show what is about to happen and offer to
-- cancel it. Cancelling is a single authenticated call that clears both columns.
