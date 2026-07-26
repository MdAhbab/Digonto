# What Digonto stores, and what deleting your account removes

Written to be checkable. Every claim below names the file or the table that
implements it, so a reader can verify it rather than trust it.

---

## 1. Your documents never leave the machine

Inference is self-hosted. The generation model is Gemma 4 E2B running under Ollama on
the same virtual machine as the API, so a passport scan, a bank statement or a
solvency letter is read by a model on that machine and is never sent to any external
provider.

This is enforced, not just intended. `app/llm/router.py` refuses a request carrying
document content on the path that could reach a remote provider, and
`backend/tests/test_agents_live.py` asserts that refusal against the live model. A
remote fallback exists for ordinary text questions when the local model is
unavailable; it cannot be reached by anything holding your document.

Files at rest are encrypted with AES-256-GCM. Each document has its own key, and that
key is wrapped by a key derived for your account alone through HKDF-SHA256
(`app/security/vault_crypto.py`). One account's key cannot open another account's
document, which `backend/tests/test_vault_crypto.py` verifies by trying.

## 2. What is stored while your account is open

- Your email address, display name, and password hash (Argon2id; the password itself
  is never stored).
- Whatever you fill into your profile, which is optional: age, address, gender,
  education history, budget.
- The countries and programmes you shortlist.
- Questions you ask and the answers given, with the citations for each.
- Documents you upload and the fields extracted from them.
- Your consent settings, which you can change at any time.

You can download all of it with `GET /me/export`.

## 3. Deleting your account

`DELETE /me` schedules deletion for **30 days** from the request. The response tells
you the exact date. Nothing is removed at that moment, and every session is signed
out.

**Why there is a wait.** Deletion used to be immediate and irreversible, which is the
wrong default when the data is your visa paperwork. A mistyped confirmation, a moment
of panic, or somebody else using your session destroyed the encryption keys along with
the record, and no recovery was possible. During the 30 days you can sign in with your
password and press one button to keep the account. After the 30 days a nightly job
erases everything (`app/workers/retention.py`, `purge_due_accounts`).

**What is erased.** Your account row, profile, questions, answers, citations,
conversations, uploaded documents and the encrypted files behind them, extracted
document fields, shortlisted countries and programmes, plans, budgets, funding
matches, interview sessions and reports, notifications, consent records, and every
training sample derived from your corrections.

`backend/tests/test_account_deletion.py` proves this rather than asserting it. One
test walks every table in the database that has a column referring to a user and fails
if any row still points at the deleted account, so a table added in future is covered
without anyone remembering to update the test.

**What survives, and why.** Two things, and they are both listed here because a
deletion promise with unlisted exceptions is not a promise.

1. **Event records, with your user id removed.** The event log is what makes the rest
   of this document checkable: it is how anyone can verify the system did what it
   claims. Your rows stay in it with `user_id` set to `NULL`, so the history of "an
   answer was given at this time citing this snapshot" survives while no longer naming
   anybody. Events are deleted outright after 180 days by the ordinary retention rule.

2. **Aggregate daily counts.** One row per day holding numbers such as how many
   questions were asked and how many were refused
   (`app/workers/insights.py`, `events.db.daily_insights`). There is no column in that
   table that could hold an identifier, and any breakdown smaller than five students is
   suppressed rather than published, because a count of one describes a person. Nothing
   in it can be traced back to you, which is why erasing it would remove nothing about
   you.

Feedback you sent through the form is kept, with your account link and any email
address you gave both removed. A report that a page is broken is about the product
rather than about you, and a maintainer may still be working from it.

## 4. What we do not do

We do not sell data, share it with consultancies, or use it for advertising. There is
no advertising on the service.

We do not build a per-student profile for business or research purposes. The nightly
report described above is counts only. If that ever changes, it would require a
consent setting you can see and switch off, an entry in this document, inclusion in
`GET /me/export`, and deletion when your account is deleted. Anything less would mean
this page is not accurate, which is the one outcome that is not acceptable.

We do not train the model on your data unless you turn on the `improve_model` consent.
If you turn it off later, `POST /me/consents/withdraw` deletes the samples already
collected and flags every model adapter that was trained on them for human review,
because "you can withdraw consent" means nothing if the data has already been trained
in and stays there.

## 5. What we cannot promise

Answers cite official sources, and the system refuses rather than guesses when no
source supports an answer. It cannot tell you that an official page is itself wrong.

The nightly crawl reaches only pages a plain HTTP request can read. Three registered
sources refuse automated clients, and we do not disguise the crawler to get past that.
Those are listed as unwatched with a reachable alternative for the same country.

Digonto is not a substitute for legal or immigration advice, and no answer here binds
any embassy, university, or government.

---

*Questions about anything on this page can go through the feedback form on the home
page, which works without an account.*
