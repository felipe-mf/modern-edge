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
