# Decisions log

Every place where the sources conflicted or the materials were ambiguous, what we decided and why.
Entries cite what was observed in the provided dataset as evidence; the code itself derives everything
from the data, contracts and APIs at run time. The pipeline copies this file to `output/decisions_log.md`
and appends the conflicts it detects on each run.

## Environment and access

**D-01. Client system credentials.** The credentials are the assessment values published in each
`API.md`. They are defaults in `docker-compose.yml` (overridable through `.env`) so that a plain
`docker compose up` works with no extra setup. They are not real secrets; real deployments would
inject them from a secret store.

**D-02. Reaching the client systems from our containers.** Default URLs use
`host.docker.internal`, mapped with `extra_hosts: host-gateway`. Verified from a container on this
machine. Any other location is set through `PAYROLL_URL`, `DISPATCH_URL`, `FINANCE_URL`.

**D-03. Transient errors are retried everywhere it is safe.** Observed: dispatch returns 429 with
`Retry-After` and intermittent `502` HTML pages from its proxy; payroll returns 503 during
processing windows. Reads retry on 429/5xx and network errors with backoff (honoring
`Retry-After`). The payroll POST is never blindly retried (see payroll decisions).

**D-04. Reporting period.** Not hard-coded. Taken from `PERIOD` when set, otherwise inferred from the
time clock data.

**D-08. Finding the input files.** Files are found by folder (as laid out in `data_guide.md`) and by
their content, not by exact name: the two punch layouts and the site code list are told apart by their
header row, the call-out log by a header containing Date, Caller and Message on any sheet. Office lock
files (`.~lock...#`, `~$...`) are skipped.

## Reading the sources

**D-09. Claude reads documents; code checks what it read.** Contracts, amendments and the wage schedule
are prose with loose tables, and the PAFs are scans with no text layer. Claude extracts them into fixed
schemas. Every building name, post count, fee, markup, rate and burden it returns must be printed in the
document text; anything that is not goes to `exceptions.csv` with low confidence. Claude never decides
whether a form takes effect: a PAF takes effect only if every approval row is signed, checked in code.

**D-10. Extraction cache.** Each Claude answer is stored in Postgres under a hash of the model, schema,
instructions and input. A re-run on the same files returns the same answer at no cost, and works without
an API key. Changing the prompt or schema changes the hash, so an old answer is never reused for a new
question. Without a key, uncached documents are skipped and listed in `exceptions.csv`.

**D-11. Punch event names.** The time clock firmware update renamed events. Old `IN`/`OUT`/`BREAK_OUT`/
`BREAK_IN` and new `CLOCK_IN`/`CLOCK_OUT`/`MEAL_START`/`MEAL_END` map to `IN`/`OUT`/`MEAL_START`/
`MEAL_END`. Unknown events are reported, not dropped.

**D-12. Punch times.** The old layout prints local time with no zone; the new one prints ISO time with a
UTC offset. Both record the building's wall-clock time, so the local time is kept as written and the
offset is stored separately.

**D-13. Reassigned dispatch postings.** Some postings were assigned, unassigned and assigned again. The
posting's history is replayed in time order: the last `ASSIGNED` counts and an `UNASSIGNED` clears it.

**D-14. Report control totals.** Each ERP report prints its own totals (invoice register total, AR record
count, GL department and entity totals). Parsers re-add what they read and compare. All six reports of
the provided dataset tie exactly. A mismatch would be listed in `exceptions.csv`.

## Documentation inconsistencies

**D-05. Backup note templates file name.** `docs/data_guide.md` refers to `billing_note_formats.md`;
the file provided is `backup_note_templates.md`. We treat them as the same document.

## Rates

**D-06. Base rate of a covering floater.** The CBA says floaters are paid at the rate of the post
they cover; the KPI definitions say base rate "belongs to the covering employee". The general ledger
and the invoices both price floaters at their own classification (observed: a Porter floater covering
a Supervisor post booked at the Porter rate in the GL; a Porter floater covering a Cleaner post invoiced
at the Porter rate). We follow the KPI definition, which matches how Finance books and bills: the
covering employee's own HR job class, at the union wage schedule (union members) or the rate card
(non-union and temporary staff).

**D-07. Overtime dollars vs. the GL overtime account.** The GL overtime account (5110) holds only the
0.5x premium; the straight-time part of an overtime shift sits in straight-time wages. The KPI defines
overtime dollars as hours x base rate x 1.5, so the KPI will not equal account 5110. We follow the
definition. Labor cost uses the full GL, so margin is unaffected.
