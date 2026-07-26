-- Per-student nightly report rows (app/workers/student_reports.py).
--
-- In app.db rather than events.db, and that placement is the whole safety argument.
-- `user_id` carries `ON DELETE CASCADE`, so the 30-day account purge removes a student's
-- reports in the same statement that removes their account, without any code having to
-- remember to. A report keyed to an account that no longer exists is exactly the quiet
-- survival `docs/privacy.md` promises does not happen, and a foreign key is a stronger
-- guarantee of that than a line in a purge routine.
--
-- The payload is a JSON object of counts: questions asked, refusal rate, documents held
-- and flagged, plan progress, scholarship matches, interviews completed, and the country
-- codes the student is applying to. It holds no name, no email address, no home district,
-- no age, no gender, and no text the student wrote. The report says what the account did,
-- not who owns it.
--
-- JSON rather than a wide table with a column per metric: the metric set will change as
-- the product does, and a schema migration per metric would mean either freezing the
-- report or accumulating nullable columns nobody reads.
CREATE TABLE IF NOT EXISTS student_reports (
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day          TEXT NOT NULL,               -- 'YYYY-MM-DD', UTC
  payload      TEXT NOT NULL CHECK (json_valid(payload)),
  generated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, day)
);

CREATE INDEX IF NOT EXISTS idx_student_reports_day ON student_reports(day DESC);
