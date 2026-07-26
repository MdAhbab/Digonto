-- Reconcile plan step keys with the generator's templates.
--
-- `plan_steps.step_key` is the identity of a step across re-plans, and
-- `PlanRepo.upsert_step` matches on it correctly. The problem was that two places
-- invented keys independently: `_STEP_TEMPLATES` in app/services/planner_service.py
-- uses `english_test`, `sop` and `apply`, while `app/db/seed_demo.py` wrote `ielts`,
-- `sop_draft` and `applications` for the same three steps.
--
-- Nothing failed loudly. The first `POST /planner/regenerate` simply found no row for
-- `english_test`, inserted one, and left the seeded `ielts` row beside it. A demo plan
-- of seven steps became ten, three of them near-duplicate pairs where one copy carried
-- the student's real progress and the other said "upcoming". The timeline showed both.
--
-- seed_demo.py now uses the template keys, so a fresh database cannot produce this. A
-- database that has already been seeded and regenerated still holds the duplicates, and
-- deleting the wrong copy of the pair would erase the student's recorded progress. So
-- the pair is merged in the safe direction: the legacy row keeps its status,
-- completed_at and history, and the generated placeholder is removed.
--
-- `plan_changes.step_id` is `ON DELETE SET NULL`, so a change entry that pointed at the
-- discarded placeholder keeps its text and its citation and loses only the step link.
-- That is the right trade: the record of what changed is worth more than the pointer.

-- 1. Where both keys exist for one plan, drop the generated copy.
--
--    Identified by having no `completed_at` and a status of 'upcoming', which is what
--    `regenerate` writes and what a step the student has touched never looks like. The
--    guard means a legitimately upcoming canonical step is never removed unless a
--    legacy twin exists to take its place.
DELETE FROM plan_steps
 WHERE step_key IN ('english_test', 'sop', 'apply')
   AND completed_at IS NULL
   AND status = 'upcoming'
   AND EXISTS (
        SELECT 1 FROM plan_steps legacy
         WHERE legacy.plan_id = plan_steps.plan_id
           AND legacy.step_key = CASE plan_steps.step_key
                                   WHEN 'english_test' THEN 'ielts'
                                   WHEN 'sop'          THEN 'sop_draft'
                                   WHEN 'apply'        THEN 'applications'
                                 END
       );

-- 2. Rename the surviving legacy rows onto the canonical keys.
--
--    Guarded by NOT EXISTS so that a plan where step 1 could not remove the twin (a
--    canonical step the student had already completed, for instance) is left exactly as
--    it is rather than hitting the UNIQUE constraint. Such a plan keeps both rows, which
--    is untidy and is strictly better than failing the migration for every deployment.
UPDATE plan_steps
   SET step_key = 'english_test'
 WHERE step_key = 'ielts'
   AND NOT EXISTS (SELECT 1 FROM plan_steps c
                    WHERE c.plan_id = plan_steps.plan_id AND c.step_key = 'english_test');

UPDATE plan_steps
   SET step_key = 'sop'
 WHERE step_key = 'sop_draft'
   AND NOT EXISTS (SELECT 1 FROM plan_steps c
                    WHERE c.plan_id = plan_steps.plan_id AND c.step_key = 'sop');

UPDATE plan_steps
   SET step_key = 'apply'
 WHERE step_key = 'applications'
   AND NOT EXISTS (SELECT 1 FROM plan_steps c
                    WHERE c.plan_id = plan_steps.plan_id AND c.step_key = 'apply');

-- 3. Repoint dependency lists at the renamed keys.
--
--    `depends_on` is a JSON array of step keys, and a dependency naming `ielts` after
--    the rename resolves to nothing, which silently breaks the ordering the Timeline
--    Reactor uses to decide what moves when a date shifts. Plain string replacement is
--    safe here because these keys appear only as whole quoted elements and none of them
--    is a substring of another key in the template set.
UPDATE plan_steps
   SET depends_on = replace(
         replace(
           replace(depends_on, '"ielts"', '"english_test"'),
         '"sop_draft"', '"sop"'),
       '"applications"', '"apply"')
 WHERE depends_on LIKE '%"ielts"%'
    OR depends_on LIKE '%"sop_draft"%'
    OR depends_on LIKE '%"applications"%';
