"""Idempotent demo/judge data seed for `app.db`.

Judges must land in a populated product: an empty account demonstrates
nothing. This module creates one realistic student (the judge account) and
one moderator account, then a full, internally consistent scenario around
the student: profile, targets at real institutions, vault documents (with
the encryption path genuinely exercised), a Truth Ledger with a pending
moderation item, scholarships, a mixed-status plan, answered questions with
citations plus one refusal, and a completed interview.

**Idempotency.** `profiles.user_id` is the primary key for the one-row-per-
student profile table, so "does the judge already have a profile" is an
exact, cheap marker for "has the full seed already run". `seed_demo` checks
that marker before doing anything beyond ensuring the two accounts exist,
and returns immediately if it is set. The judge and moderator user rows are
each guarded independently by an email lookup, so calling this on every
boot (as `app/main.py`'s lifespan does) never creates a duplicate row
anywhere, however many times the process restarts.

**Atomicity.** Everything after the account checks is written through a
single call to `Database.write`, which hands this module the live writer
connection for the duration of one explicit transaction. That is what makes
it safe for the many rows below to reference each other's `lastrowid`
(a snapshot's id feeding a passage insert, a plan's id feeding its steps,
and so on): if anything raises, the whole batch rolls back rather than
leaving a half-seeded student behind.

**Scope.** Only `app.db`. Nothing here touches `events.db` or `learn.db`;
the brief only asks for the former, and inventing event/replay rows nobody
else's code expects would be pure risk for no requirement.

**is_demo.** Only `users.is_demo` exists as a column in this schema (see
docs/database.md: no other table carries it), so that is the only place
this module sets it. Everything else seeded here hangs off the judge user's
id through foreign keys and cascades away if that user row is ever deleted;
institutions, programmes, portals, snapshots, and scholarships are treated
as shared catalogue/reference data (the same status real crawled or
curated rows would have), not per-user demo state.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app.agents.prohori import _mechanical_findings
from app.config import Settings
from app.db.connection import Databases
from app.repositories._util import new_ulid
from app.security.passwords import hash_password
from app.security.vault_crypto import encrypt_file

log = logging.getLogger(__name__)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_date(d: date) -> str:
    return d.isoformat()


# --------------------------------------------------------------------------
# Account bootstrap (outside the main transaction: each is its own tiny,
# independently idempotent write, and password hashing is CPU-bound work
# that has no business running inside the writer's critical section).
# --------------------------------------------------------------------------


async def _ensure_user(
    dbs: Databases,
    *,
    email: str,
    password: str,
    display_name: str,
    role: str,
    now_iso: str,
) -> int | None:
    if not email or not password:
        log.warning(
            "seed_demo: email/password not configured for role=%s, skipping account", role
        )
        return None
    existing = await dbs.app.fetch_val("SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        return int(existing)
    user_id = await dbs.app.execute(
        """INSERT INTO users
           (public_id, email, password_hash, display_name, role, status,
            email_verified, lang_pref, theme_pref, is_demo, created_at)
           VALUES (?, ?, ?, ?, ?, 'active', 1, 'bn', 'system', 1, ?)""",
        (new_ulid(), email, hash_password(password), display_name, role, now_iso),
    )
    log.info("seed_demo: created demo account role=%s email=%s", role, email)
    return int(user_id)


async def seed_demo(dbs: Databases, settings: Settings) -> None:
    """Create the judge/moderator accounts and a full demo scenario.

    Safe to call on every boot: `app/main.py`'s lifespan does exactly that,
    guarded by `APP_ENV != production` and `SEED_DEMO_DATA`.
    """
    if settings.is_production or not settings.seed_demo_data:
        return

    now_iso = _ts(_now())

    judge_id = await _ensure_user(
        dbs,
        email=settings.seed_judge_email,
        password=settings.seed_judge_password,
        display_name="Rafiul Karim",
        role="student",
        now_iso=now_iso,
    )
    await _ensure_user(
        dbs,
        email=settings.seed_moderator_email,
        password=settings.seed_moderator_password,
        display_name="Nusrat Jahan",
        role="moderator",
        now_iso=now_iso,
    )

    if judge_id is None:
        # No judge account, no student to hang the rest of the scenario off.
        return

    already_seeded = await dbs.app.fetch_val(
        "SELECT 1 FROM profiles WHERE user_id = ?", (judge_id,)
    )
    if already_seeded:
        log.info("seed_demo: demo dataset already present, skipping")
        return

    judge_row = await dbs.app.fetch_one("SELECT public_id FROM users WHERE id = ?", (judge_id,))
    assert judge_row is not None
    judge_public_id = judge_row["public_id"]

    async def _run(conn: aiosqlite.Connection) -> dict[str, Any]:
        return await _seed_all(
            conn, judge_id=judge_id, judge_public_id=judge_public_id, settings=settings
        )

    stats = await dbs.app.write(_run)
    log.info("seed_demo: seeded demo dataset rows=%s", stats)


# --------------------------------------------------------------------------
# The full scenario, one atomic transaction.
# --------------------------------------------------------------------------


async def _seed_all(
    conn: aiosqlite.Connection, *, judge_id: int, judge_public_id: str, settings: Settings
) -> dict[str, int]:
    counts: dict[str, int] = {}

    async def run(sql: str, params: tuple = ()) -> int:
        cur = await conn.execute(sql, params)
        return cur.lastrowid or 0

    async def bump(table: str, n: int = 1) -> None:
        counts[table] = counts.get(table, 0) + n

    async def portal_by_url(sql: str, params: tuple, url: str) -> int:
        """Insert a demo portal, or adopt the registry row with the same URL.

        Migration 015 seeds the real watched-portal registry, and two of its
        entries are the same URLs this demo scenario attaches snapshots to. A
        plain INSERT would hit the UNIQUE constraint on `portals.url` and abort
        the whole seed transaction, so the existing row is reused instead: the
        demo timeline then hangs off the production portal, which is more
        realistic than a duplicate anyway.
        """
        await conn.execute(sql, params)
        cur = await conn.execute("SELECT id FROM portals WHERE url = ?", (url,))
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError(f"portal row for {url} neither inserted nor found")
        return int(row[0])

    await conn.execute("BEGIN IMMEDIATE")
    try:
        now = _now()
        today = now.date()
        now_iso = _ts(now)

        # -- 1. Profile -----------------------------------------------------
        await run(
            """INSERT INTO profiles
               (user_id, display_name, home_district, degree_level, field_of_study,
                cgpa, cgpa_scale, graduation_year, english_test, english_overall,
                english_sub, budget_bdt, intake_target, study_gap_years, updated_at)
               VALUES (?, ?, ?, 'master', 'Computer Science', 3.62, 4.0, 2023,
                       'ielts', 7.0, ?, ?, 'Fall 2027', 1, ?)""",
            (
                judge_id,
                "Rafiul Karim",
                "Cumilla",
                json.dumps({"listening": 7.5, "reading": 7.0, "writing": 6.5, "speaking": 7.0}),
                2_500_000 * 100,  # BDT 25,00,000 (2.5 million) in poisha
                now_iso,
            ),
        )
        await bump("profiles")

        # -- 2. Portals -------------------------------------------------------
        uk_fetch2 = now - timedelta(days=6)
        uk_fetch1 = now - timedelta(days=46)
        ca_fetch2 = now - timedelta(days=3)
        ca_fetch1 = now - timedelta(days=50)

        uk_url = "https://www.gov.uk/student-visa/money"
        portal_uk = await portal_by_url(
            """INSERT OR IGNORE INTO portals
               (public_id, url, kind, country_code, label, parser_key, crawl_cron,
                enabled, last_fetch_at, last_status, consecutive_failures, created_at)
               VALUES (?, ?, 'government', 'uk', 'gov.uk/student-visa', 'generic',
                       '0 */6 * * *', 1, ?, 'ok', 0, ?)""",
            (new_ulid(), uk_url, _ts(uk_fetch2), _ts(uk_fetch1)),
            uk_url,
        )
        await bump("portals")
        ca_url = (
            "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
            "study-canada/study-permit/financial-proof.html"
        )
        portal_ca = await portal_by_url(
            """INSERT OR IGNORE INTO portals
               (public_id, url, kind, country_code, label, parser_key, crawl_cron,
                enabled, last_fetch_at, last_status, consecutive_failures, created_at)
               VALUES (?, ?, 'government', 'ca', 'canada.ca/study-permit', 'generic',
                       '0 */6 * * *', 1, ?, 'ok', 0, ?)""",
            (new_ulid(), ca_url, _ts(ca_fetch2), _ts(ca_fetch1)),
            ca_url,
        )
        await bump("portals", 1)

        # -- 3. Snapshots and passages ----------------------------------------
        # UK: the financial-evidence passage changes between the two
        # snapshots (a real amount increase); the document-checklist passage
        # does not.
        uk1_p1 = (
            "Living costs for a course in London are £1,334 per month, for up "
            "to 9 months. Outside London, the amount is £1,023 per month."
        )
        uk2_p1 = (
            "Living costs for a course in London are £1,483 per month, for up "
            "to 9 months. Outside London, the amount is £1,136 per month."
        )
        uk_p2 = (
            "You must provide a bank statement or letter from your bank "
            "showing you have held the required amount for a consecutive "
            "28-day period. The 28-day period must end no more than 31 days "
            "before you apply for your student visa."
        )

        async def _make_snapshot(
            portal_id: int, fetched_at: datetime, passages: list[tuple[str, str]]
        ) -> tuple[int, str, list[int]]:
            body = "\n\n".join(text for _, text in passages)
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            storage_path = f"snapshots/{portal_id}/{content_hash}.html"
            snap_public_id = new_ulid()
            snap_id = await run(
                """INSERT INTO snapshots
                   (public_id, portal_id, content_hash, storage_path, http_status,
                    byte_size, fetched_at, retired_at)
                   VALUES (?, ?, ?, ?, 200, ?, ?, NULL)""",
                (
                    snap_public_id,
                    portal_id,
                    content_hash,
                    storage_path,
                    len(body),
                    _ts(fetched_at),
                ),
            )
            await bump("snapshots")
            passage_ids: list[int] = []
            for ordinal, (section_path, text) in enumerate(passages, start=1):
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                pid = await run(
                    """INSERT INTO passages
                       (snapshot_id, ordinal, section_path, text, text_hash, lang, char_count)
                       VALUES (?, ?, ?, ?, ?, 'en', ?)""",
                    (snap_id, ordinal, section_path, text, text_hash, len(text)),
                )
                passage_ids.append(pid)
                await bump("passages")
            return snap_id, snap_public_id, passage_ids

        snap_uk1, snap_uk1_pub, pass_uk1 = await _make_snapshot(
            portal_uk,
            uk_fetch1,
            [("Requirements > Financial evidence", uk1_p1), ("Requirements > Documents", uk_p2)],
        )
        snap_uk2, snap_uk2_pub, pass_uk2 = await _make_snapshot(
            portal_uk,
            uk_fetch2,
            [("Requirements > Financial evidence", uk2_p1), ("Requirements > Documents", uk_p2)],
        )

        ca1_p1 = (
            "You must show proof you can pay for your tuition fees and living "
            "expenses. For a single applicant, this means at least CAD "
            "$20,635 for a year, in addition to your tuition. Add CAD $10,000 "
            "for each family member who comes with you."
        )
        ca2_p1 = (
            "Applicants must show proof they can pay for tuition fees and "
            "living expenses. For a single applicant, this means at least "
            "CAD $20,635 for a year, in addition to tuition. Add CAD $10,000 "
            "for each family member who comes with you."
        )
        ca_p2 = (
            "You need proof of funds such as bank statements for the past 4 "
            "months, a Guaranteed Investment Certificate (GIC) from a "
            "participating Canadian bank, or proof of a student or education "
            "loan."
        )
        snap_ca1, snap_ca1_pub, pass_ca1 = await _make_snapshot(
            portal_ca,
            ca_fetch1,
            [("Requirements > Financial evidence", ca1_p1), ("Requirements > Documents", ca_p2)],
        )
        snap_ca2, snap_ca2_pub, pass_ca2 = await _make_snapshot(
            portal_ca,
            ca_fetch2,
            [("Requirements > Financial evidence", ca2_p1), ("Requirements > Documents", ca_p2)],
        )

        # -- 4. Passage diffs: one pending review, one auto-resolved cosmetic -
        await run(
            """INSERT INTO passage_diffs
               (portal_id, from_snapshot_id, to_snapshot_id, change_type,
                old_passage_id, new_passage_id, similarity, category,
                category_confidence, classified_at, needs_review, created_at)
               VALUES (?, ?, ?, 'modified', ?, ?, 0.89, NULL, NULL, NULL, 1, ?)""",
            (portal_uk, snap_uk1, snap_uk2, pass_uk1[0], pass_uk2[0], _ts(uk_fetch2)),
        )
        await bump("passage_diffs")
        await run(
            """INSERT INTO passage_diffs
               (portal_id, from_snapshot_id, to_snapshot_id, change_type,
                old_passage_id, new_passage_id, similarity, category,
                category_confidence, classified_at, needs_review, created_at)
               VALUES (?, ?, ?, 'modified', ?, ?, 0.97, 'cosmetic', 0.95, ?, 0, ?)""",
            (portal_ca, snap_ca1, snap_ca2, pass_ca1[0], pass_ca2[0], _ts(ca_fetch2), _ts(ca_fetch2)),
        )
        await bump("passage_diffs", 1)

        # -- 5. Institutions and programmes ------------------------------------
        inst_manchester = await run(
            """INSERT INTO institutions
               (public_id, country_code, name, city, website, portal_id, verified,
                is_partner, created_at)
               VALUES (?, 'uk', 'University of Manchester', 'Manchester',
                       'https://www.manchester.ac.uk', ?, 1, 0, ?)""",
            (new_ulid(), portal_uk, now_iso),
        )
        inst_ucl = await run(
            """INSERT INTO institutions
               (public_id, country_code, name, city, website, portal_id, verified,
                is_partner, created_at)
               VALUES (?, 'uk', 'University College London', 'London',
                       'https://www.ucl.ac.uk', ?, 1, 0, ?)""",
            (new_ulid(), portal_uk, now_iso),
        )
        inst_toronto = await run(
            """INSERT INTO institutions
               (public_id, country_code, name, city, website, portal_id, verified,
                is_partner, created_at)
               VALUES (?, 'ca', 'University of Toronto', 'Toronto',
                       'https://www.utoronto.ca', ?, 1, 0, ?)""",
            (new_ulid(), portal_ca, now_iso),
        )
        await bump("institutions", 3)

        prog_manchester = await run(
            """INSERT INTO programmes
               (public_id, institution_id, name, degree_level, field_of_study,
                duration_months, tuition_amount, tuition_currency, intake_months,
                min_cgpa, min_english, deadline_at, source_snapshot_id, updated_at)
               VALUES (?, ?, 'MSc Advanced Computer Science', 'master',
                       'Computer Science', 12, 2680000, 'GBP', ?, 3.0, 6.5,
                       '2027-05-01', ?, ?)""",
            (new_ulid(), inst_manchester, json.dumps(["September"]), snap_uk2, now_iso),
        )
        prog_ucl = await run(
            """INSERT INTO programmes
               (public_id, institution_id, name, degree_level, field_of_study,
                duration_months, tuition_amount, tuition_currency, intake_months,
                min_cgpa, min_english, deadline_at, source_snapshot_id, updated_at)
               VALUES (?, ?, 'MSc Data Science', 'master', 'Data Science', 12,
                       3660000, 'GBP', ?, 3.3, 7.0, '2027-03-15', ?, ?)""",
            (new_ulid(), inst_ucl, json.dumps(["September"]), snap_uk2, now_iso),
        )
        prog_toronto = await run(
            """INSERT INTO programmes
               (public_id, institution_id, name, degree_level, field_of_study,
                duration_months, tuition_amount, tuition_currency, intake_months,
                min_cgpa, min_english, deadline_at, source_snapshot_id, updated_at)
               VALUES (?, ?, 'Master of Science in Applied Computing', 'master',
                       'Computer Science', 16, 4500000, 'CAD', ?, 3.3, 6.5,
                       '2027-01-15', ?, ?)""",
            (new_ulid(), inst_toronto, json.dumps(["September", "January"]), snap_ca2, now_iso),
        )
        await bump("programmes", 3)

        # -- 6. Student targets (3 across 2 countries) -------------------------
        target_manchester = await run(
            """INSERT INTO student_targets
               (public_id, user_id, programme_id, visa_type, rank, status, created_at)
               VALUES (?, ?, ?, 'student', 0, 'applying', ?)""",
            (new_ulid(), judge_id, prog_manchester, now_iso),
        )
        await run(
            """INSERT INTO student_targets
               (public_id, user_id, programme_id, visa_type, rank, status, created_at)
               VALUES (?, ?, ?, 'student', 1, 'considering', ?)""",
            (new_ulid(), judge_id, prog_ucl, now_iso),
        )
        await run(
            """INSERT INTO student_targets
               (public_id, user_id, programme_id, visa_type, rank, status, created_at)
               VALUES (?, ?, ?, 'study_permit', 2, 'submitted', ?)""",
            (new_ulid(), judge_id, prog_toronto, now_iso),
        )
        await bump("student_targets", 3)

        # -- 7. Vault documents (6), encrypted for real ------------------------
        vault_dir = settings.vault_dir / judge_public_id
        vault_dir.mkdir(parents=True, exist_ok=True)

        # Dynamic, relative to "today" so the two Prohori triggers below
        # (passport margin, near-term expiry) always fire, whenever this
        # actually runs: the fallback travel-date estimate in
        # app/agents/prohori.py is `today + 270 days`, and the required
        # passport margin on top of that is another 180 days (450 days
        # total). 300 days comfortably trips it without depending on a
        # hardcoded calendar date going stale.
        doc_specs = [
            (
                "passport",
                "passport_rafiul_karim.pdf",
                today - timedelta(days=365 * 5 - 65),
                today + timedelta(days=300),
            ),
            (
                "transcript",
                "transcript_buet_cse.pdf",
                today - timedelta(days=540),
                None,
            ),
            (
                "english_test",
                "ielts_trf_rafiul_karim.pdf",
                today - timedelta(days=180),
                today - timedelta(days=180) + timedelta(days=730),
            ),
            (
                "bank_statement",
                "bank_statement_dbbl_jul.pdf",
                today - timedelta(days=10),
                today + timedelta(days=45),
            ),
            (
                "sop",
                "sop_manchester_msc_cs.pdf",
                today - timedelta(days=20),
                None,
            ),
            (
                "recommendation",
                "recommendation_letter_prof_rahman.pdf",
                today - timedelta(days=15),
                None,
            ),
        ]

        documents_for_prohori: list[dict[str, Any]] = []
        for kind, filename, issued_on, expires_on in doc_specs:
            placeholder = (
                f"DEMO PLACEHOLDER DOCUMENT - {kind} - Rafiul Karim - "
                "synthetic content generated by backend/app/db/seed_demo.py, "
                "not a real document."
            ).encode("utf-8")
            sha256 = hashlib.sha256(placeholder).hexdigest()
            ciphertext, wrapped_dek, nonce = encrypt_file(
                placeholder, user_id=judge_id, settings=settings
            )
            storage_path = vault_dir / f"{sha256}.enc"
            storage_path.write_bytes(ciphertext)

            doc_public_id = new_ulid()
            doc_id = await run(
                """INSERT INTO documents
                   (public_id, user_id, kind, original_name, storage_path, mime_type,
                    byte_size, sha256, wrapped_dek, nonce, issued_on, expires_on,
                    status, uploaded_at)
                   VALUES (?, ?, ?, ?, ?, 'application/pdf', ?, ?, ?, ?, ?, ?,
                           'extracted', ?)""",
                (
                    doc_public_id,
                    judge_id,
                    kind,
                    filename,
                    str(storage_path),
                    len(placeholder),
                    sha256,
                    wrapped_dek,
                    nonce,
                    _iso_date(issued_on) if issued_on else None,
                    _iso_date(expires_on) if expires_on else None,
                    now_iso,
                ),
            )
            await bump("documents")
            documents_for_prohori.append(
                {
                    "id": doc_id,
                    "kind": kind,
                    "expires_on": _iso_date(expires_on) if expires_on else None,
                    "deleted_at": None,
                    "fields": [],
                }
            )

        # -- 8. Prohori audit: real mechanical findings, not invented ones ----
        # Same function production Prohori runs
        # (app/agents/prohori._mechanical_findings), called directly against
        # the documents just inserted so the findings persisted below are
        # guaranteed to be exactly what the live agent would compute.
        findings = _mechanical_findings(documents_for_prohori, profile=None, target=None)

        audit_id = await run(
            """INSERT INTO audits (public_id, user_id, target_id, agent, status,
               started_at, finished_at)
               VALUES (?, ?, ?, 'prohori', 'complete', ?, ?)""",
            (new_ulid(), judge_id, target_manchester, now_iso, now_iso),
        )
        await bump("audits")
        for finding in findings:
            await run(
                """INSERT INTO audit_findings
                   (public_id, audit_id, document_id, code, severity, title_en,
                    title_bn, detail_en, detail_bn, evidence, action_en, action_bn,
                    snapshot_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    new_ulid(),
                    audit_id,
                    finding["document_id"],
                    finding["code"],
                    finding["severity"],
                    finding["title_en"],
                    finding["title_bn"],
                    finding["title_en"],
                    finding["title_bn"],
                    json.dumps(finding["evidence"]) if finding.get("evidence") else None,
                    None,
                    None,
                ),
            )
            await bump("audit_findings")

        # -- 9. Scholarships and criteria (6) -----------------------------------
        seeded_scholarship_ids: list[int] = []
        scholarships = [
            (
                "Commonwealth Shared Scholarship",
                "Commonwealth Scholarship Commission",
                "uk",
                ["master"],
                None,
                "full",
                None,
                "GBP",
                "2027-01-15",
                "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-shared-scholarships/",
                [
                    ("cgpa_min", "gte", "3.0", 1, 1.0),
                    ("degree_level", "eq", "master", 1, 1.0),
                    ("nationality", "eq", "Bangladesh", 1, 1.0),
                ],
            ),
            (
                "Chevening Scholarship",
                "UK Foreign, Commonwealth & Development Office",
                "uk",
                ["master"],
                None,
                "full",
                None,
                "GBP",
                "2026-11-03",
                "https://www.chevening.org/",
                [
                    ("work_experience_years", "gte", "2", 1, 1.0),
                    ("degree_level", "eq", "master", 1, 1.0),
                    ("english_overall", "gte", "6.5", 0, 0.8),
                ],
            ),
            (
                "GREAT Scholarships Bangladesh",
                "British Council",
                "uk",
                ["master"],
                ["Computer Science", "Engineering", "Creative Industries"],
                "tuition_only",
                1000000,
                "GBP",
                "2027-03-31",
                "https://www.britishcouncil.org.bd/en/study-uk/great-scholarships",
                [
                    ("nationality", "eq", "Bangladesh", 1, 1.0),
                    ("degree_level", "eq", "master", 1, 1.0),
                    (
                        "field_of_study",
                        "in",
                        json.dumps(["STEM", "Creative Industries", "Agriculture"]),
                        0,
                        0.6,
                    ),
                ],
            ),
            (
                "DAAD EPOS Scholarship",
                "German Academic Exchange Service",
                "de",
                ["master"],
                ["Computer Science", "Engineering", "Public Policy"],
                "full",
                None,
                "EUR",
                "2026-10-15",
                "https://www.daad.de/en/study-and-research-in-germany/scholarships/",
                [
                    ("degree_level", "eq", "master", 1, 1.0),
                    (
                        "field_of_study",
                        "in",
                        json.dumps(["Computer Science", "Engineering", "Public Policy"]),
                        1,
                        1.0,
                    ),
                    ("cgpa_min", "gte", "3.0", 0, 0.7),
                ],
            ),
            (
                "Ontario Graduate Scholarship",
                "Government of Ontario",
                "ca",
                ["master", "phd"],
                None,
                "partial",
                1500000,
                "CAD",
                "2026-09-30",
                "https://www.ontario.ca/page/ontario-graduate-scholarship",
                [
                    ("cgpa_min", "gte", "3.3", 1, 1.0),
                    ("degree_level", "in", json.dumps(["master", "phd"]), 1, 1.0),
                ],
            ),
            (
                "University of Toronto International Scholar Award",
                "University of Toronto",
                "ca",
                ["master"],
                None,
                "stipend_only",
                500000,
                "CAD",
                "2027-02-01",
                "https://www.sgs.utoronto.ca/awards/",
                [
                    ("degree_level", "eq", "master", 1, 1.0),
                    ("cgpa_min", "gte", "3.5", 0, 0.5),
                ],
            ),
        ]
        for (
            name,
            provider,
            country,
            degree_levels,
            fields,
            coverage_type,
            amount,
            currency,
            deadline_at,
            url,
            criteria,
        ) in scholarships:
            sid = await run(
                """INSERT INTO scholarships
                   (public_id, name, provider, country_code, degree_levels, fields,
                    coverage_type, amount, currency, deadline_at, url, snapshot_id,
                    verified, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, 1, ?)""",
                (
                    new_ulid(),
                    name,
                    provider,
                    country,
                    json.dumps(degree_levels),
                    json.dumps(fields) if fields else None,
                    coverage_type,
                    amount,
                    currency,
                    deadline_at,
                    url,
                    now_iso,
                ),
            )
            await bump("scholarships")
            seeded_scholarship_ids.append(sid)
            for criterion_key, operator, value, is_hard, weight in criteria:
                await run(
                    """INSERT INTO scholarship_criteria
                       (scholarship_id, criterion_key, operator, value, is_hard, weight)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sid, criterion_key, operator, value, is_hard, weight),
                )
                await bump("scholarship_criteria")

        # -- 9b. Funding matches ------------------------------------------------
        #
        # `GET /funding/scholarships` reads `funding_matches`, not the award
        # catalogue, because the page ranks awards against one student. Without
        # a seeded match set the Funding page is empty until somebody presses
        # rematch, which is the wrong first impression on a fresh deployment.
        #
        # These scores are deterministic placeholders derived from how many of
        # each award's hard criteria this seeded profile satisfies, and they are
        # replaced by Khoji's real scoring the moment `POST /funding/rematch`
        # runs. The reason strings say so, rather than pretending a model wrote
        # them.
        for rank, sid in enumerate(seeded_scholarship_ids, start=1):
            hard_criteria = [
                r
                for r in await conn.execute_fetchall(
                    "SELECT criterion_key, is_hard FROM scholarship_criteria WHERE scholarship_id = ?",
                    (sid,),
                )
            ]
            met = sum(1 for r in hard_criteria if not r[1])
            score = round(met / len(hard_criteria), 2) if hard_criteria else 0.5
            match_id = await run(
                """INSERT INTO funding_matches
                   (public_id, user_id, scholarship_id, score, rank, eligible,
                    kb_version_id, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
                (new_ulid(), judge_id, sid, score, rank, 1 if score >= 0.5 else 0, now_iso),
            )
            await bump("funding_matches")
            for criterion_key, is_hard in hard_criteria:
                await run(
                    """INSERT INTO match_reasons
                       (match_id, criterion_key, met, reason_en, reason_bn, weight)
                       VALUES (?, ?, ?, ?, ?, 1.0)""",
                    (
                        match_id,
                        criterion_key,
                        0 if is_hard else 1,
                        "Not yet scored by the eligibility agent. Press Rematch for a live assessment.",
                        "যোগ্যতা এজেন্ট এখনো এটি মূল্যায়ন করেনি। সরাসরি মূল্যায়নের জন্য পুনরায় মেলান চাপুন।",
                    ),
                )
                await bump("match_reasons")

        # -- 9c. FX rate, solvency rule, and one computed budget ---------------
        #
        # The Funding page has three panels. The award list above fills one.
        # The other two read `fx_rates`, `solvency_rules` and `budgets`, and
        # 404 when those are empty, so the page is half broken without this.
        #
        # The solvency figure is the published UK maintenance requirement for
        # a course in London: 1,483 pounds per month for a maximum of nine
        # months, which is 13,347 pounds, held for 28 consecutive days. It is
        # attached to the seeded UK portal snapshot so the citation the page
        # renders points at a real archived row rather than nowhere.
        await run(
            """INSERT INTO fx_rates (base, quote, rate, source, as_of)
               VALUES ('GBP', 'BDT', 152.0, 'seeded demonstration rate', ?)""",
            (now_iso[:10],),
        )
        await bump("fx_rates")

        await run(
            """INSERT INTO solvency_rules
               (country_code, visa_type, amount, currency, hold_days,
                basis_note_en, basis_note_bn, snapshot_id, effective_from)
               VALUES ('uk', 'student', 13347, 'GBP', 28, ?, ?, ?, ?)""",
            (
                "Courses in London: 1,483 pounds of living costs per month, "
                "for a maximum of nine months, held for 28 consecutive days.",
                "লন্ডনের কোর্সের ক্ষেত্রে: মাসে ১,৪৮৩ পাউন্ড জীবনযাত্রার খরচ, "
                "সর্বোচ্চ নয় মাসের জন্য, টানা ২৮ দিন ধরে রাখতে হবে।",
                snap_uk2,
                now_iso[:10],
            ),
        )
        await bump("solvency_rules")

        # Tuition is the Manchester programme's own figure converted at the
        # rate above; living, travel and the visa fee follow the same rule.
        # gap_bdt is the arithmetic, not an estimate: cost minus funding.
        tuition_bdt = 4_712_000
        living_bdt = 2_029_000
        travel_bdt = 145_000
        visa_fee_bdt = 118_000
        awards_bdt = 1_500_000
        own_funds_bdt = 3_800_000
        gap_bdt = (
            tuition_bdt + living_bdt + travel_bdt + visa_fee_bdt
            - awards_bdt - own_funds_bdt
        )
        await run(
            """INSERT INTO budgets
               (public_id, user_id, target_id, tuition_bdt, living_bdt, travel_bdt,
                visa_fee_bdt, awards_bdt, own_funds_bdt, gap_bdt,
                solvency_required_bdt, fx_rate_used, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 152.0, ?)""",
            (
                new_ulid(),
                judge_id,
                target_manchester,
                tuition_bdt,
                living_bdt,
                travel_bdt,
                visa_fee_bdt,
                awards_bdt,
                own_funds_bdt,
                gap_bdt,
                int(13347 * 152),
                now_iso,
            ),
        )
        await bump("budgets")

        # -- 10. Plan: 7 steps, mixed statuses, 2 changes -----------------------
        plan_id = await run(
            """INSERT INTO plans (public_id, user_id, target_id, intake_label,
               generated_at, updated_at)
               VALUES (?, ?, ?, 'Fall 2027', ?, ?)""",
            (new_ulid(), judge_id, target_manchester, now_iso, now_iso),
        )
        await bump("plans")

        steps = [
            (
                "ielts",
                1,
                "Nov 2025",
                "2025-11-15",
                "Take the IELTS Academic test",
                "আইইএলটিএস একাডেমিক পরীক্ষা দিন",
                "A 7.0 overall clears every programme's English requirement "
                "in this shortlist.",
                "সামগ্রিক ৭.০ স্কোর এই শর্টলিস্টের প্রতিটি প্রোগ্রামের ইংরেজি "
                "শর্ত পূরণ করে।",
                "done",
                [],
                "2025-11-20",
            ),
            (
                "shortlist",
                2,
                "Jan 2026",
                "2026-01-31",
                "Shortlist universities and programmes",
                "বিশ্ববিদ্যালয় ও প্রোগ্রাম শর্টলিস্ট করুন",
                "Manchester, UCL, and Toronto chosen against budget and CGPA fit.",
                "বাজেট ও সিজিপিএ বিবেচনায় ম্যানচেস্টার, ইউসিএল এবং টরন্টো "
                "বেছে নেওয়া হয়েছে।",
                "done",
                [],
                "2026-01-25",
            ),
            (
                "sop_draft",
                3,
                "Mar 2026",
                "2026-03-31",
                "Draft the statement of purpose",
                "স্টেটমেন্ট অব পারপাস খসড়া করুন",
                "First draft checked against the transcript and IELTS result "
                "for consistency.",
                "ট্রান্সক্রিপ্ট ও আইইএলটিএস ফলাফলের সঙ্গে সামঞ্জস্য যাচাই করে "
                "প্রথম খসড়া তৈরি হয়েছে।",
                "done",
                ["ielts"],
                "2026-03-28",
            ),
            (
                "applications",
                4,
                "Jul 2026",
                "2026-08-15",
                "Submit university applications",
                "বিশ্ববিদ্যালয়ে আবেদন জমা দিন",
                "Toronto submitted; Manchester and UCL in progress this month.",
                "টরন্টোতে আবেদন জমা হয়েছে; ম্যানচেস্টার ও ইউসিএল-এর আবেদন এই "
                "মাসে চলছে।",
                "active",
                ["shortlist", "sop_draft"],
                None,
            ),
            (
                "solvency",
                5,
                "Aug 2026",
                "2026-09-01",
                "Arrange bank solvency certificate",
                "ব্যাংক সলভেন্সি সার্টিফিকেট প্রস্তুত করুন",
                "Must cover the updated GBP 1,483/month London living-cost "
                "figure for a consecutive 28-day period.",
                "লন্ডনের হালনাগাদ মাসিক ১,৪৮৩ পাউন্ড জীবনযাত্রার খরচ একটানা "
                "২৮ দিন অ্যাকাউন্টে দেখাতে হবে।",
                "active",
                [],
                None,
            ),
            (
                "offer_accept",
                6,
                "Nov 2026",
                "2026-11-30",
                "Accept offer and pay deposit",
                "অফার গ্রহণ করে ডিপোজিট প্রদান করুন",
                "Waiting on decisions before committing the deposit.",
                "ডিপোজিট দেওয়ার আগে সিদ্ধান্তগুলোর জন্য অপেক্ষা করা হচ্ছে।",
                "upcoming",
                ["applications"],
                None,
            ),
            (
                "visa",
                7,
                "Jun 2027",
                "2027-07-01",
                "Apply for student visa",
                "স্টুডেন্ট ভিসার জন্য আবেদন করুন",
                "Filed once the CAS/offer, solvency evidence, and IELTS TRF "
                "are all in hand.",
                "সিএএস/অফার, সলভেন্সি প্রমাণ এবং আইইএলটিএস টিআরএফ হাতে এলে "
                "আবেদন করা হবে।",
                "upcoming",
                ["offer_accept", "solvency"],
                None,
            ),
        ]
        step_ids: dict[str, int] = {}
        for (
            step_key,
            order_idx,
            month_label,
            due_at,
            title_en,
            title_bn,
            desc_en,
            desc_bn,
            status,
            depends_on,
            completed_at,
        ) in steps:
            source_snapshot_id = snap_uk2 if step_key == "solvency" else None
            step_id = await run(
                """INSERT INTO plan_steps
                   (public_id, plan_id, step_key, order_idx, month_label, due_at,
                    title_en, title_bn, desc_en, desc_bn, status, depends_on,
                    lead_days, source_snapshot_id, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 14, ?, ?)""",
                (
                    new_ulid(),
                    plan_id,
                    step_key,
                    order_idx,
                    month_label,
                    due_at,
                    title_en,
                    title_bn,
                    desc_en,
                    desc_bn,
                    status,
                    json.dumps(depends_on),
                    source_snapshot_id,
                    completed_at,
                ),
            )
            step_ids[step_key] = step_id
            await bump("plan_steps")

        await run(
            """INSERT INTO plan_changes
               (public_id, plan_id, step_id, trigger, text_en, text_bn, source_label,
                snapshot_id, event_id, seen_at, created_at)
               VALUES (?, ?, ?, 'portal_change', ?, ?, ?, ?, NULL, NULL, ?)""",
            (
                new_ulid(),
                plan_id,
                step_ids["solvency"],
                "The required London living-cost figure rose from GBP 1,334 "
                "to GBP 1,483 per month. Your solvency step now targets the "
                "new amount.",
                "লন্ডনের প্রয়োজনীয় মাসিক জীবনযাত্রার খরচ ১,৩৩৪ পাউন্ড থেকে "
                "বেড়ে ১,৪৮৩ পাউন্ড হয়েছে। আপনার সলভেন্সি ধাপ এখন নতুন "
                "অঙ্ককে লক্ষ্য করছে।",
                f"gov.uk/student-visa · {snap_uk2_pub}",
                snap_uk2,
                _ts(uk_fetch2),
            ),
        )
        await bump("plan_changes")
        await run(
            """INSERT INTO plan_changes
               (public_id, plan_id, step_id, trigger, text_en, text_bn, source_label,
                snapshot_id, event_id, seen_at, created_at)
               VALUES (?, ?, ?, 'profile_update', ?, ?, 'profile update', NULL, NULL, ?, ?)""",
            (
                new_ulid(),
                plan_id,
                step_ids["ielts"],
                "IELTS overall score of 7.0 confirmed; the English-requirement "
                "check on every shortlisted programme now passes.",
                "আইইএলটিএস সামগ্রিক স্কোর ৭.০ নিশ্চিত হয়েছে; শর্টলিস্ট করা "
                "প্রতিটি প্রোগ্রামের ইংরেজি শর্ত এখন পূরণ হচ্ছে।",
                _ts(now - timedelta(days=200)),
                _ts(now - timedelta(days=200)),
            ),
        )
        await bump("plan_changes", 1)

        # -- 11. Conversations, questions, answers, citations --------------------
        conv_uk = await run(
            """INSERT INTO conversations (public_id, user_id, title, created_at, updated_at)
               VALUES (?, ?, 'যুক্তরাজ্যে পড়াশোনার খরচ', ?, ?)""",
            (new_ulid(), judge_id, now_iso, now_iso),
        )
        conv_ca = await run(
            """INSERT INTO conversations (public_id, user_id, title, created_at, updated_at)
               VALUES (?, ?, 'কানাডা স্টাডি পারমিট', ?, ?)""",
            (new_ulid(), judge_id, now_iso, now_iso),
        )
        await bump("conversations", 2)

        async def _qa(
            *,
            conversation_id: int,
            text_raw: str,
            text_normalised: str,
            country_filter: str,
            answer_bn: str | None,
            answer_en: str | None,
            is_refusal: bool,
            refusal_reason: str,
            confidence: float | None,
            latency_ms: int,
            first_token_ms: int,
            citations: list[tuple[int, int, str]],
        ) -> None:
            q_id = await run(
                """INSERT INTO questions
                   (public_id, conversation_id, user_id, text_raw, text_normalised,
                    lang_detected, country_filter, created_at)
                   VALUES (?, ?, ?, ?, ?, 'bn', ?, ?)""",
                (
                    new_ulid(),
                    conversation_id,
                    judge_id,
                    text_raw,
                    text_normalised,
                    country_filter,
                    now_iso,
                ),
            )
            await bump("questions")
            a_id = await run(
                """INSERT INTO answers
                   (public_id, question_id, answer_bn, answer_en, confidence,
                    is_refusal, refusal_reason, kb_version_id, model_tag, served_by,
                    cache_hit, latency_ms, first_token_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'gemma4:e2b', 'local', 0, ?, ?, ?)""",
                (
                    new_ulid(),
                    q_id,
                    answer_bn,
                    answer_en,
                    confidence,
                    int(is_refusal),
                    refusal_reason,
                    latency_ms,
                    first_token_ms,
                    now_iso,
                ),
            )
            await bump("answers")
            for ordinal, (snapshot_id, passage_id, quoted_span) in enumerate(citations, start=1):
                await run(
                    """INSERT INTO answer_citations
                       (answer_id, ordinal, snapshot_id, passage_id, quoted_span)
                       VALUES (?, ?, ?, ?, ?)""",
                    (a_id, ordinal, snapshot_id, passage_id, quoted_span),
                )
                await bump("answer_citations")

        await _qa(
            conversation_id=conv_uk,
            text_raw="লন্ডনে মাস্টার্স করতে গেলে ব্যাংকে কত টাকা দেখাতে হবে?",
            text_normalised="londone masters korte gele bank e koto taka dekhate hobe",
            country_filter="uk",
            answer_bn=(
                "যুক্তরাজ্যে পড়াশোনার সময় লন্ডনে থাকলে জীবনযাত্রার খরচ হিসেবে "
                "মাসে ১,৪৮৩ পাউন্ড দেখাতে হবে, সর্বোচ্চ ৯ মাসের জন্য। লন্ডনের "
                "বাইরে হলে এই পরিমাণ মাসে ১,১৩৬ পাউন্ড। এই অর্থ একটানা ২৮ দিন "
                "ব্যাংক অ্যাকাউন্টে থাকতে হবে, এবং আবেদনের সর্বোচ্চ ৩১ দিন আগে "
                "পর্যন্ত এই সময়সীমা শেষ হতে হবে।"
            ),
            answer_en=(
                "For a course in London you must show GBP 1,483 per month for "
                "living costs, for up to 9 months (GBP 1,136 per month outside "
                "London). This amount must be held for a consecutive 28-day "
                "period ending no more than 31 days before you apply."
            ),
            is_refusal=False,
            refusal_reason="not applicable",
            confidence=0.94,
            latency_ms=5130,
            first_token_ms=612,
            citations=[
                (snap_uk2, pass_uk2[0], uk2_p1),
                (snap_uk2, pass_uk2[1], uk_p2),
            ],
        )
        await _qa(
            conversation_id=conv_uk,
            text_raw=(
                "যুক্তরাজ্যের স্টুডেন্ট ভিসার জন্য আর্থিক প্রমাণ হিসেবে কী "
                "ধরনের কাগজ জমা দিতে হবে?"
            ),
            text_normalised=(
                "juktorajjer student visar jonno arthik proman hisebe ki "
                "dhoroner kagoj joma dite hobe"
            ),
            country_filter="uk",
            answer_bn=(
                "আপনার ব্যাংক থেকে স্টেটমেন্ট বা চিঠি জমা দিতে হবে যাতে দেখা "
                "যায় প্রয়োজনীয় অর্থ একটানা ২৮ দিন আপনার অ্যাকাউন্টে ছিল। এই "
                "২৮ দিনের মেয়াদ আবেদনের সর্বোচ্চ ৩১ দিনের মধ্যে শেষ হতে হবে।"
            ),
            answer_en=(
                "You need a bank statement or letter showing the required "
                "amount was held for a consecutive 28-day period, ending no "
                "more than 31 days before you apply."
            ),
            is_refusal=False,
            refusal_reason="not applicable",
            confidence=0.90,
            latency_ms=4870,
            first_token_ms=580,
            citations=[(snap_uk2, pass_uk2[1], uk_p2)],
        )
        await _qa(
            conversation_id=conv_ca,
            text_raw=(
                "কানাডায় স্টাডি পারমিটের জন্য আর্থিক সামর্থ্যের প্রমাণ হিসেবে "
                "কত টাকা দেখাতে হয়?"
            ),
            text_normalised=(
                "canada te study permit er jonno arthik samorthyer proman "
                "hisebe koto taka dekhate hoy"
            ),
            country_filter="ca",
            answer_bn=(
                "কানাডায় স্টাডি পারমিটের আবেদনকারীকে টিউশন ফি ছাড়াও বছরে "
                "অন্তত ২০,৬৩৫ কানাডিয়ান ডলার সংস্থানের প্রমাণ দিতে হয়। সঙ্গে "
                "আসা প্রতিটি পরিবারের সদস্যের জন্য অতিরিক্ত ১০,০০০ ডলার দেখাতে "
                "হবে। এই অর্থ ব্যাংক স্টেটমেন্ট, গ্যারান্টিড ইনভেস্টমেন্ট "
                "সার্টিফিকেট (GIC), অথবা শিক্ষা ঋণের প্রমাণ দিয়ে দেখানো যায়।"
            ),
            answer_en=(
                "A study permit applicant must show at least CAD $20,635 for "
                "a year beyond tuition, plus CAD $10,000 per accompanying "
                "family member, via bank statements, a GIC, or proof of an "
                "education loan."
            ),
            is_refusal=False,
            refusal_reason="not applicable",
            confidence=0.91,
            latency_ms=5310,
            first_token_ms=640,
            citations=[
                (snap_ca2, pass_ca2[0], ca2_p1),
                (snap_ca2, pass_ca2[1], ca_p2),
            ],
        )
        await _qa(
            conversation_id=conv_uk,
            text_raw="আমেরিকায় F1 ভিসার জন্য ব্যাংকে কত টাকা থাকতে হবে?",
            text_normalised="america te f1 visa er jonno bank e koto taka thakte hobe",
            country_filter="us",
            answer_bn=(
                "আমার কাছে যুক্তরাষ্ট্রের F1 ভিসার আর্থিক সামর্থ্যের যাচাইকৃত "
                "কোনো উৎস নেই, তাই নির্দিষ্ট কোনো অঙ্ক বলা যাচ্ছে না। দূতাবাসের "
                "সরকারি ওয়েবসাইট থেকে হালনাগাদ তথ্য যাচাই করুন।"
            ),
            answer_en=(
                "I don't have a verified source for the US F1 visa financial "
                "requirement, so I can't state a figure. Please check the "
                "embassy's official page."
            ),
            is_refusal=True,
            refusal_reason="No indexed source passage covers US F1 visa financial requirements.",
            confidence=0.12,
            latency_ms=1910,
            first_token_ms=260,
            citations=[],
        )

        # -- 12. Interview session, turns, report -------------------------------
        started_at = now - timedelta(days=3, minutes=25)
        ended_at = started_at + timedelta(minutes=22)
        session_id = await run(
            """INSERT INTO interview_sessions
               (public_id, user_id, target_id, country_code, visa_type, mode,
                status, started_at, ended_at)
               VALUES (?, ?, ?, 'uk', 'student', 'text', 'complete', ?, ?)""",
            (new_ulid(), judge_id, target_manchester, _ts(started_at), _ts(ended_at)),
        )
        await bump("interview_sessions")

        turns = [
            (
                "কেন আপনি যুক্তরাজ্যকে পড়াশোনার জন্য বেছে নিয়েছেন?",
                "যুক্তরাজ্যের কম্পিউটার সায়েন্স প্রোগ্রামগুলোর গবেষণার মান এবং "
                "এক বছরের মাস্টার্স কাঠামো আমার ক্যারিয়ারের সময়ের সঙ্গে ভালোভাবে "
                "মানানসই।",
                0.88,
                0.85,
                0.80,
                None,
                "Directly answers why the UK, with a specific, checkable reason.",
                "যুক্তরাজ্য কেন, তার সুনির্দিষ্ট ও যাচাইযোগ্য কারণ সরাসরি "
                "উত্তর দিয়েছে।",
            ),
            (
                "আপনার পড়াশোনা ও থাকার খরচ কীভাবে বহন করবেন?",
                "পারিবারিক সঞ্চয় এবং বাবার ব্যবসার আয় থেকে টিউশন ও থাকার খরচ "
                "বহন করা হবে; ব্যাংক সলভেন্সি সার্টিফিকেট প্রস্তুত করা হচ্ছে।",
                0.90,
                0.82,
                0.75,
                None,
                "Consistent with the profile's declared budget and solvency step.",
                "প্রোফাইলে উল্লেখিত বাজেট ও সলভেন্সি ধাপের সঙ্গে সামঞ্জস্যপূর্ণ।",
            ),
            (
                "কেন আপনি এই নির্দিষ্ট প্রোগ্রামটি বেছে নিয়েছেন?",
                "ম্যানচেস্টারের অ্যাডভান্সড কম্পিউটার সায়েন্স প্রোগ্রামে "
                "মেশিন লার্নিং-এ নির্দিষ্ট মডিউল আছে যা আমার স্নাতক থিসিসের "
                "ধারাবাহিকতা।",
                0.86,
                0.80,
                0.78,
                None,
                "Ties the programme choice to concrete academic history.",
                "প্রোগ্রাম নির্বাচনকে সুনির্দিষ্ট একাডেমিক ইতিহাসের সঙ্গে "
                "যুক্ত করেছে।",
            ),
            (
                "পড়াশোনা শেষে আপনি কী পরিকল্পনা করছেন?",
                "স্নাতক শেষে বাংলাদেশে ফিরে একটি সফটওয়্যার প্রতিষ্ঠানে কাজ "
                "করার পরিকল্পনা আছে।",
                0.72,
                0.70,
                0.68,
                None,
                "Post-study plan is present but could name a specific "
                "employer or sector to strengthen ties to home.",
                "পড়াশোনা-পরবর্তী পরিকল্পনা আছে, তবে নির্দিষ্ট প্রতিষ্ঠান বা "
                "খাতের নাম উল্লেখ করলে দেশের সঙ্গে সম্পর্ক আরও দৃঢ় হতো।",
            ),
            (
                "আপনার ব্যাংক স্টেটমেন্টে সম্প্রতি একটি বড় অঙ্কের জমা দেখা "
                "যাচ্ছে, এটি কীসের?",
                "এটি বাবার ব্যবসার একটি জমি বিক্রির অংশ, যা আমার পড়াশোনার "
                "জন্য আলাদা করে রাখা হয়েছে।",
                0.65,
                0.60,
                0.58,
                json.dumps(
                    [
                        {
                            "turn_ordinal": 2,
                            "note": "The stated family income in turn 2 does not "
                            "fully explain this lump-sum deposit; a source "
                            "document (land sale deed) is recommended.",
                        }
                    ]
                ),
                "Plausible, but should be backed by a source document (sale "
                "deed) before the real interview.",
                "যুক্তিসঙ্গত উত্তর, তবে আসল ইন্টারভিউয়ের আগে সংশ্লিষ্ট "
                "নথি (বিক্রয় দলিল) দিয়ে প্রমাণ রাখা উচিত।",
            ),
        ]
        for ordinal, (
            question_text,
            answer_text,
            relevance,
            consistency,
            credibility,
            contradicts,
            feedback_en,
            feedback_bn,
        ) in enumerate(turns, start=1):
            answered_at = started_at + timedelta(minutes=4 * ordinal)
            await run(
                """INSERT INTO interview_turns
                   (session_id, ordinal, bank_id, question_text, answer_text,
                    audio_path, relevance, consistency, credibility, contradicts,
                    feedback_en, feedback_bn, answered_at)
                   VALUES (?, ?, NULL, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    ordinal,
                    question_text,
                    answer_text,
                    relevance,
                    consistency,
                    credibility,
                    contradicts,
                    feedback_en,
                    feedback_bn,
                    _ts(answered_at),
                ),
            )
            await bump("interview_turns")

        await run(
            """INSERT INTO interview_reports
               (public_id, session_id, overall, summary_en, summary_bn, strengths,
                weaknesses, created_at)
               VALUES (?, ?, 0.78, ?, ?, ?, ?, ?)""",
            (
                new_ulid(),
                session_id,
                "A generally strong, consistent performance. Financial and "
                "academic answers were specific and checkable; the post-study "
                "plan and the large-deposit follow-up were the two weakest "
                "points and should be tightened before a real interview.",
                "সার্বিকভাবে শক্তিশালী ও সামঞ্জস্যপূর্ণ পারফরম্যান্স। আর্থিক ও "
                "একাডেমিক উত্তরগুলো সুনির্দিষ্ট ও যাচাইযোগ্য ছিল; পড়াশোনা-"
                "পরবর্তী পরিকল্পনা এবং বড় জমার প্রশ্নের উত্তর দুটি সবচেয়ে "
                "দুর্বল দিক ছিল এবং আসল ইন্টারভিউয়ের আগে আরও শক্তিশালী করা "
                "উচিত।",
                json.dumps(
                    [
                        "Clear, checkable reason for choosing the UK and this programme",
                        "Financial narrative consistent with the seeded profile and plan",
                    ]
                ),
                json.dumps(
                    [
                        "Post-study plan lacks a specific employer or sector",
                        "Large bank deposit needs a supporting document, not just an explanation",
                    ]
                ),
                now_iso,
            ),
        )
        await bump("interview_reports")

        await conn.execute("COMMIT")
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    return counts
