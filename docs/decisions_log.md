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

## Identity across sources

**D-15. Canonical building names.** The KPI definitions require the Schedule B names. Every other
identifier (finance site, ledger department, HR location code, time clock site name or code, dispatch
site, invoice site, budget name) is linked to one of them in `building_aliases`, with the method and
confidence of each link. Name matching expands common address abbreviations (TWR, PLZ, HSE, ANX, BLDG,
1 -> ONE) and refuses a match when two buildings score alike (e.g. a bare "Meridian").

**D-16. Departments and HR locations.** A finance site links a ledger department to a building. An HR
location links through its department. A department with no finance site (observed: 460, Bramwell
Annex, missing from the finance site list) is linked through personnel forms that print the location
code next to the building name ("BLD-06 (Bramwell Annex)"), and failing that by elimination. Departments
Finance lists as non-client sites (the float pool) are excluded.

**D-17. Time clock sites are confirmed by who punches there.** Each time clock site's name match must
agree with the HR home building of the permanent employees punching there. Observed: every site agrees
(91-100%), including both Bramwell Annex codes (S-106 and S-116) and both old-layout spellings. Where the
name gives nothing, a site with 80%+ of punches from one building is linked to it at medium confidence.

**D-18. Employee ids.** Badge, payroll and dispatch ids are linked to HR by number only when the name in
that source matches the HR name; otherwise by a single clear name match. Observed: the dispatch worker
"Miguel Martinez" carries HR number E10075, which does not exist; the name matches E10057 (Miguel
Martinez, floater), so the worker is linked to E10057 at medium confidence.

**D-19. Home building over time.** HR roster, updated by personnel forms with every approval signed, as
of their effective date. Observed: Mimoza Leka's transfer (all three approvals) moves her from Meridian
Plaza to Meridian One on 10/19, although the roster still shows Meridian Plaza; Brian Walker's transfer
has only the HR approval and has no effect; Jennifer Moore's termination and Wilfredo Gonzalez's hire
agree with the roster.

**D-20. Contract terms as of the period end.** The latest agreement per building, with amendments
effective on or before the last day of the period applied in date order. Observed: Corlett Building goes
from 3+7 to 3+8 posts under Amendment No. 2 (effective 09/01). Backup note template comes from each
agreement's coverage backup rules: names required -> Template A, names forbidden -> Template B.

**D-21. Clients and legal entities.** The legal entity is the contractor named in the agreement, matched
to the finance entity list. Observed: Corlett's agreement is with Northgate Facility Staffing (NFS) and
its invoices are issued by NFS to customer 2207, which is not in the customer master; the master lists
Corlett as NBS customer C-1004. Revenue follows the invoice site, so it is attributed to Corlett
Building either way; both findings are in `exceptions.csv`.

**D-22. Payroll status differs from HR.** Observed: Wilfredo Gonzalez is ACTIVE in HR and PENDING_SETUP
in payroll. Absences for such employees are held for review with that reason instead of being posted.

**D-23. Labor budget.** The FY26 labor budget is out of date (last updated in June, 2025 rates, a
terminated employee still listed). It is loaded for reference only and never used for headcount or rates.

## KPIs

**D-24. Active headcount.** Counted on the last day of the period from the resolved home building
(D-19). An employee whose termination date is on or before that day counts as terminated.

**D-25. Scheduled shifts and holidays.** The KPI scope says shifts run Monday to Friday; Schedule B
excludes "holidays observed by the Building" but no holiday calendar is provided. Every weekday is
counted. October has no US federal holiday that closes buildings, so this has no effect here.

**D-26. Fill rate and overtime from dispatch.** Postings are taken by shift date within the period.
Cancelled postings are excluded; a posting is filled when its status is FILLED. Overtime uses the
fill type of the posting's final assignment (D-13); each such shift adds 8 hours at the posting's site.

**D-27. Wage rate effective date.** The CBA says a rate takes effect on the first day of the first full
payroll week on or after the date shown, but the payroll week is not defined anywhere. The rate in
force on a day is the latest one whose date shown is on or before that day. This only matters in the
first days of a new rate year, not in the reporting period.

**D-28. Labor cost period.** The GL labor report for 2026-10 includes the week ending 11/01/26. The
ledger assigns it to October, so it is included; labor cost is exactly the report's department total.

**D-29. AR aging.** As of the last day of the period. Documents dated after it are not yet receivable
(observed: NFS-7124, dated 11/02 for October service, counts as October revenue but is not open AR on
10/31 and is not in the AR report either). A payment that names no invoice in the report would be aged
as an unapplied credit and reported; none occur in this dataset.

## Call-outs and payroll

**D-30. What Claude does with a call-out.** Claude reads each log row and chat message into a fixed
schema: is it an absence, the reason, the name and building as written, the shift, the days in the
caller's own words, and any time the caller states. It gets the message text only, no timestamps, so
it cannot confuse a phone timestamp with something the caller said. Code then checks the answer
against the text: the words for each day and the name must appear in the message, and a stated time
is only used if its hour is written there. Dates, people, notice, codes and payroll are all code.

**D-31. When notice was given.** 14.2 measures notice from when the call-out is received. Phone call:
the time reception logged it. Voicemail: the phone system's timestamp (its year taken from the log
date). One voicemail has no timestamp but the caller says "it's about 11 in the morning"; that time is
used (it is earlier than the time reception logged it) and the absence is flagged medium. If a
voicemail had no time at all, the logged time would be used as an upper bound, and a late-notice code
from it is held. Chat: the time the employee texted the manager when the manager states it (Gloria
"texted me this morning around 10:32", posted 13:20), otherwise the post time. The chat export has no
time zone; it is read as the buildings' local time, like the log.

**D-32. Which day.** today/tonight = the day the call-out was received; tomorrow = the next day; a
weekday = its next occurrence. "Tomorrow" said before the first shift starts (00:25) can mean the day
that has just begun, and the same weekday as today can mean today or next week: both are ambiguous.
The dispatch posting created for the absence settles an ambiguous date (Zoran 10/29); otherwise the
absence is held. Bereavement "tonight and Friday" is two absences.

**D-33. Which employee.** Full name, name with an initial, or first name only, among people employed
on the absence date; then the building and shift the caller gave, using their assignment that day
(D-19). Two Maria Gonzalez work nights; the voicemail says only "the building", and the dispatch
posting for that night (Halcyon) settles it. A first name alone (chat: "Jelena", "Gloria") is accepted
when building and shift leave one person, and flagged medium.

**D-34. Duplicates.** One absence per employee per date, whichever channel reported it; the earliest
report is kept. A chat message relaying an absence is a report even when it says the employee "called
the front desk too" (Andre 10/09), so the duplicate is caught by the rule, not by the wording. A call
that only confirms an earlier one ("called back to confirm") is not an absence.

**D-35. Coding.** In the guide's order: eligibility, notice, balance; absences in date order.
- Late notice (LTN) and unpaid codes do not use a sick day; only SKP does.
- An employee with no sick days left who also gave late notice gets LTN, because the guide checks
  notice before balance.
- The guide's eligibility step names the 14.3 probation period, so a clinic day also needs 90 days of
  employment; an ineligible clinic visit is PER, as the guide says.
- A clinic day already used this year is PER: the visit is not sick leave and the guide gives no
  other code for it.
- Bereavement needs an immediate relative (14.5); a fourth bereavement day, or a relative that cannot
  be verified, is held for review.
- HR's sick balance is as of the first day of the period (its column name says so); clinic use is for
  the calendar year.

**D-36. What is held for review.** Unidentified or ambiguous employee or date, a message Claude could
not read or whose extraction does not match the text, a date outside the open pay period or on a
weekend, an unknown shift where notice matters, payroll status other than ACTIVE (Wilfredo,
PENDING_SETUP, coded SKU because he is in probation), and any answer from payroll other than success.
Held absences are still coded, so a reviewer sees what would be written.

**D-37. Writing to payroll exactly once.** Payroll has no idempotency key, and on the first live run
it answered 503 "processing window" to POSTs it had in fact stored (3 of 4 times). So the writer asks
payroll before each POST and again before any retry, adopts what is already there, never overwrites a
different code (held instead), and after the batch is processed voids any extra copy. Every request
is kept in `payroll_audit`, and `payroll_ledger` keeps the last state per absence; both survive
reruns. A second full run made 0 writes. `PAYROLL_DRY_RUN=true` reads payroll but never writes;
its rows show `final_status` DRY_RUN.

**D-38. Output references.** `source_ref` is the spreadsheet row number as Excel shows it (header =
row 1) for the log, and the message timestamp (`YYYY-MM-DD HH:MM:SS`, as printed) for the chat.
Reception log rows that are not absences are listed in exceptions.csv; ordinary chat conversation is
kept in `callout_events` but not listed.

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
