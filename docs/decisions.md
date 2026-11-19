# Decisions log

Business and engineering decisions that are not obvious from the code, newest
first. This is the public version: agency and people names, per-company
results and workspace IDs stay in the private repository.

## 2026-11-19 · Automate up to the send button, not the send

**Why not automate sending:** for 10 founders, each message is a one-shot
first impression and sending by hand costs minutes. LinkedIn automation tools
break LinkedIn's terms and put the main professional asset at risk. No emails
are collected: finding them costs Clay credits, cold email needs warmed
domains, and UK/EU contacts raise GDPR questions. Human approval of every
message is also a model many agencies sell. Email at scale can be revisited
for wave 2.

**What is automated:** `engine/attio_followups.py` creates Attio tasks for
each company moved to "Contacted", counted in business days from the move:
day 3 check the connection and send the message, day 8 follow-up, day 13 note
to the backup contact, each with its draft. Reaching "Replied" or later closes
the open tasks. Idempotent: a marker in each task's text. Scheduled with the
Windows Task Scheduler on weekdays at 09:00 (`scheduler/`); if the PC was off,
it runs at the next start.

## 2026-11-19 · Company locations in Attio

Attio's own enrichment filled the location for about 60% of the companies.
`attio_sync.py` now writes a location only when the record has none (never
over Attio's data or a value typed by hand). Source order: Clay record → Apollo
→ directory listing, converted to ISO alpha-2. Two parsing bugs caught on the
way: "New York, NY" read NY as a country (2-letter values now count only if
they are known country codes) and "San Jose, CA" could become Canada.

## 2026-11-19 · Re-check before sending

Every quoted fact and open role in the wave-1 drafts was checked again, page
by page, before release. One posting had changed to "US only, send me a video
of something you built": the primary contact moved to the person who posted
it, and the message now offers a contractor path with the walkthrough as the
video. Each change was posted to Attio as a dated update note.

## 2026-11-13 · Wave 1 outreach drafts

**Who:** the top 10 of band A, after my own labels (one A became B on team
geography, the next company took its place).

**Channel and cadence:** LinkedIn, sent by hand. Connection note to the
primary contact (≤ 300 characters) → message after they accept (≤ ~110
words) → follow-up after 5 business days → short note to the backup contact
after 10. Where a job is open, also apply to the posting.

**Content rules:** 2-3 facts per company, each with its source (website page
or Clay data), checked before sending; proof is real work only; remote from
Brazil and contractor openness stated up front; one low-friction ask.

**Fact check:** four overstatements in the first draft were fixed (a rank, a
"top 10", geography coverage and how many companies Claude double-checked).

## 2026-11-13 · Pipeline in Attio

A list "GTM Talent Pipeline" on Companies with stages Qualified → Contact
found → Drafted → Contacted → Replied → Call → Trial project → Offer → Closed
and fields for band, fit score, Clay tier, team geography, hiring signal, why
it fits, and primary and backup contacts. Companies are asserted by domain;
decision makers are People with name, title, LinkedIn and company. **No email,
no phone.**

**What broke:** `POST /v2/lists` returned HTTP 500 three times, so the list is
created by hand in the Attio UI and the sync adds fields, stages and entries.
A second run created duplicate people because Attio stores LinkedIn URLs
without the trailing slash Clay returns, so the exact-match lookup never hit.
`find_person` now normalizes the URL and keeps the oldest record; the
duplicates were deleted.

## 2026-11-13 · Decision makers from Clay Search

People query on the free plan:

```
clay.filter_to_companies((<company LinkedIn URLs or domains>))
and experiences.any(is_current = true and seniority in ("Founder", "Owner", "C-suite", "Partner"))
limit 2 by clay_company_id
```

People search works on the free plan (only company → people cross-entity
filters do not). It spends the search quota (100 results per rolling 30 days),
not data credits. Every band-A company got a primary contact (CEO or founder);
most got a backup (COO, CRO, Head of Ops). Names and LinkedIn URLs stay in a
gitignored folder and in Attio.

## 2026-11-13 · Team geography from Clay

One credit per company for current employees by country, spent on every
company in bands A and B and the disputes (about 100) instead of filling
missing company records, which were almost all band C. 99 of 100 completed.
The numbers confirmed what my labels had guessed by hand. A first "North
America + Europe" list missed part of Europe, so it was widened and the runs
were re-read for free.

**Missed date:** the run was planned for the credit renewal day, but nothing
was scheduled, so it waited a day for a session. Follow-ups are now scheduled.

## 2026-11-08 · Clay first for everything Clay can do

Every step Clay can do runs in Clay. Apollo, public APIs and reading public
pages are fallbacks, used only when Clay cannot do the step on the current
plan, and each one is recorded here. This engine is also a public case for
agencies that sell Clay: "why Apollo in a Clay case?" needs a deliberate,
documented answer, not a default.

## 2026-11-08 · Clay enrichment waterfall fills the Apollo gaps

CSV upload → Enrich company (Clay, `cpj-enrich-company-v2`, 0.5 credit) →
conditional "Clay found nothing?" → Datagma fallback (0.4 credit). The
fallback only runs, and only costs, when Clay returns no company. First run:
23 companies, Clay found all of them at step 1, 11.5 credits. One company moved
from B to A on the new data.

## 2026-11-08 · Company enrichment went to Apollo first (reversed)

Company records first came from Apollo's `organizations/enrich` for cost
reasons on free plans. Apollo's credits ran out after ~138 companies, leaving
66 without a record, so the gaps went to the Clay waterfall above and Clay
became the default.

## 2026-11-08 · Clay free plan cannot filter companies by people or jobs

`people.exists(...)` and `jobs.exists(...)` in Clay Search need a paid plan.
The queries are ready in `engine/sources/clay_signals.py`. On the free plan,
hiring comes from public ATS APIs and careers pages.
