-- Student feedback, collected in the product rather than on a form somewhere else.
--
-- The reason this is a table and not a mailto: link is that the useful signal is
-- the one attached to the page where the confusion happened. "I do not understand
-- the solvency figure" is a support request; the same sentence with `page` set to
-- /funding is a defect report about a specific screen.
CREATE TABLE IF NOT EXISTS feedback (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,        -- 'FB-01J8XQ...'

  -- NULL for feedback sent while signed out, and NULL again once the author
  -- deletes their account. ON DELETE SET NULL rather than CASCADE: a defect report
  -- is about the product, not about the person, so it stays readable after the
  -- account is purged and stops being attributable at the same moment. Deleting it
  -- would also give a student a way to erase a bug report a maintainer is working
  -- from, which serves nobody.
  user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,

  kind         TEXT NOT NULL CHECK (kind IN
                 ('bug','confusing','wrong_answer','idea','praise','other')),
  message      TEXT NOT NULL,
  -- The route the student was on. Recorded from the client because the server
  -- cannot know which single-page route was rendered.
  page         TEXT,
  lang         TEXT NOT NULL DEFAULT 'bn' CHECK (lang IN ('bn','en')),

  -- Optional, and only what the student types into the field. Never copied from
  -- the account: someone signed in who leaves this blank has chosen not to be
  -- contacted, and pre-filling it from `users.email` would quietly overrule that.
  -- Cleared by the purge together with user_id.
  contact_email TEXT,

  created_at   TEXT NOT NULL,
  reviewed_at  TEXT,
  reviewed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  -- What the maintainer did about it. Visible only in the moderator console.
  disposition  TEXT CHECK (disposition IN ('fixed','planned','declined','duplicate','answered'))
);

-- The moderator console reads unreviewed first, newest first.
CREATE INDEX IF NOT EXISTS idx_feedback_queue
  ON feedback(reviewed_at, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
