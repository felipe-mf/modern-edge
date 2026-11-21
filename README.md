# Northgate data spine and call-out automation

ModernEdge AI Solutions Engineer assessment. One `docker compose up` does the following:

- reads Northgate's files and its three systems (payroll, dispatch, finance);
- resolves one record per employee, building, department and client;
- codes every call-out under the union rules and writes it to payroll exactly once;
- prices billable coverage;
- writes the required files to `./output`.

A React interface shows the building view, the KPI panel, the review queue, payroll submissions and a
chatbot. Every figure links to its source record.

- `docs/decisions_log.md`: every conflict between sources and every ambiguity, what was decided and why.
- `AI_USAGE.md`: where AI tools were used and what I verified myself.

## Setup

Requirements: Docker with Compose. Nothing else on the host.

1. Start the client systems from the assessment package: `cd mock_systems && docker compose up --build`.
2. Put the client files in `./data`, or point `DATA_DIR` at them.
3. `cp .env.example .env` and set `ANTHROPIC_API_KEY` (see Configuration).
4. `docker compose up --build`.

The pipeline runs once and exits. Then the API starts and the interface is at <http://localhost:8080>.
The outputs are in `./output`:

| File | Contents |
|---|---|
| `kpis_by_building.csv` | One row per building, columns as the package README lists them |
| `ar_aging.csv` | Open receivables per aging bucket |
| `payroll_submissions.csv` | One row per absence decided on: written to payroll or held for review |
| `backup_notes/<posting_id>.txt` | One note per billable coverage shift, in its client's template |
| `exceptions.csv` | Every record the system could not resolve or chose to flag |
| `decisions_log.md` | The decisions log, followed by the conflicts this run met (from `exceptions.csv`) |

Running `docker compose up` again re-runs the pipeline, and that is safe:

- payroll is never written twice (D-37);
- document extractions are cached in Postgres, so a re-run on the same files makes no model calls.

`docker compose down -v` deletes the database, including the cache, the payroll audit and the review
decisions.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `./data` | Client files, mounted read-only |
| `PAYROLL_URL`, `DISPATCH_URL`, `FINANCE_URL` | `http://host.docker.internal:808{1,2,3}` | Client systems |
| `PAYROLL_API_KEY`, `DISPATCH_CLIENT_ID`, `DISPATCH_CLIENT_SECRET`, `FINANCE_USER`, `FINANCE_PASSWORD` | values in each `API.md` | Client system credentials (D-01) |
| `ANTHROPIC_API_KEY` | none | Needed for documents and messages not yet in the cache |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Contracts, amendment, wage schedule, scanned forms |
| `ANTHROPIC_CALLOUT_MODEL` | `claude-sonnet-5-5` | Call-out messages (D-39) |
| `ANTHROPIC_CHAT_MODEL` | `claude-sonnet-5-5` | The chatbot |
| `PAYROLL_DRY_RUN` | `false` | `true`: decide every absence and read payroll, but never write to it |
| `PERIOD` | inferred | Reporting month `YYYY-MM`; inferred from the time clock data when unset |
| `DB_PORT`, `API_PORT`, `WEB_PORT` | `5432`, `8000`, `8080` | Host ports, bound to 127.0.0.1 |

Without an API key the pipeline still runs. Documents and messages that are not in the cache are
skipped and listed in `exceptions.csv`.

## Architecture

```
docker compose up
  db        Postgres 16. Source tables are rebuilt on every run; state tables (model answer cache,
            payroll ledger and audit, review decisions) persist across runs.
  pipeline  Python, runs once:
              ingest files and APIs -> resolve identities -> code call-outs -> write to payroll
              -> billing -> KPIs -> ./output
  api       FastAPI over the same database: the views for the interface, review actions, chatbot.
            Starts after the pipeline has finished.
  web       React + TypeScript (Vite build) served by nginx; /api is proxied to the api service.
```

Every ingested row keeps a `source_ref` back to where it came from: a file line, a spreadsheet row, a
chat message or an API record. KPI drill-downs, the building view, the review queue and the chatbot all
link to it, and the interface opens the original record.

The model only reads text, into fixed schemas (D-09, D-30):

- contracts, the wage schedule and the scanned forms;
- each call-out message.

Code checks every value against the document text and makes every decision: identities, dates,
notice, absence codes, payroll writes, billable amounts and KPIs.

| Package | What it does |
|---|---|
| `northgate/clients` | HTTP clients for the three systems: retries with backoff on 429/5xx, OAuth token refresh, cursor paging, finance report jobs |
| `northgate/parsers` | The finance reports (invoice register, AR, GL labor), each checked against its printed totals |
| `northgate/ingest` | Files and documents into Postgres: HR roster, both time clock layouts, call-out log, chat, contracts, wage schedule, personnel forms, labor budget |
| `northgate/resolve` | Canonical buildings, departments, clients and employees, with method and confidence per link |
| `northgate/callouts` | Call-out extraction, date and employee resolution, duplicates, notice and the Article 14 coding rules |
| `northgate/payroll` | The exactly-once payroll writer with dry run, audit log and ledger |
| `northgate/billing` | Billable coverage, invoice line matching, backup notes |
| `northgate/kpis` | Operations and financial KPIs, AR aging |
| `northgate/api` | Interface views, review actions, chatbot |
| `northgate/outputs.py` | The output files |
| `web/` | The interface |

### Payroll writes

Payroll has no idempotency key, and it can store a submission while answering 503. So the writer:

- asks payroll whether the absence already exists before each POST and before any retry;
- adopts what is already there;
- never overwrites a different code;
- voids any extra copy once the batch is processed.

Every request and response is kept in `payroll_audit`.

Some absences the rules cannot settle: an unknown or ambiguous employee or date, a payroll status
other than ACTIVE, or an extraction that does not match the text. These are held with a reason and
appear in the review queue. Approving one sends it through the same writer (D-37, D-46).

## How margin and unbilled coverage are calculated

Both follow `docs/kpi_definitions.md` from the package.

**Revenue** is the sum of every invoice line whose service period is the reporting month. That
includes every line type (contract, coverage, sundry, credit), whatever the invoice date or issuing
entity. Each line is attributed to a building through its finance site name (D-15).

**Labor cost** is the building's department total in the GL labor report for the month, every account,
both entities.

- The department is linked to the building through Finance's site list, or through the personnel forms
  when Finance has no site for it (D-16).
- The report's own totals are checked (D-14).

**Gross margin** = revenue − labor cost. **Gross margin %** = gross margin ÷ revenue, as a decimal.
Example from the provided data: Corlett Building, 67,035.88 − 60,722.85 = 6,313.03, or 0.0942.

**Unbilled coverage** applies only at buildings whose agreement makes coverage billable.

1. Billable coverage: every dispatch posting in the month, call-out or vacation, whose status is
   FILLED (D-40).
2. Its amount, rounded to the cent per shift:
   `8 × base rate × (1.5 if filled on overtime, else 1) × (1 + burden) × (1 + markup)`.
   - The base rate is the covering employee's own HR job class, in force on the shift date: the union
     wage schedule for members, the rate card for others (D-06, D-27).
   - Burden is the covering employee's pay schedule rate from the wage schedule.
   - The markup comes from the agreement as amended.
3. Each coverage line on the invoices is matched to a posting:
   - by the `ref P-...` it prints;
   - otherwise by building, service date and shift, then the replacement's name, then the exact amount.

   A line that still fits several postings, or none, is not guessed and goes to exceptions (D-41).
4. Unbilled coverage is the billable postings with no matched line: their count and the sum of their
   amounts. At fixed-fee buildings it is 0 (D-44).

Example from the provided data: Corlett Building has 2 unbilled shifts, 558.84 + 299.82 = 858.66. All
27 invoiced coverage lines matched a posting at exactly the amount the formula gives.

## Tests

```
uv sync
uv run pytest                      # parsers, resolution, call-out rules, payroll writer, billing, KPIs, API
uv run ruff check northgate tests
uv run python -m northgate.smoke   # connectivity check against the client systems
cd web && npm ci && npx tsc -b      # interface type check
```

The tests use small synthetic data written for them, never the client files. The payroll writer is
tested against a fake payroll that:

- stores a submission but loses the answer (503 or a timeout);
- rejects a submission;
- already holds duplicates or a different code.

The end-to-end checks were run by hand:

- a dry run first, then a live run;
- payroll read back for duplicates;
- a second full run made 0 writes;
- every output figure recomputed from the sources (see `AI_USAGE.md`).

## What I deferred, and why

- **A live feed for the building view.** The view shows the data of the last pipeline run, not a
  stream of new punches and postings. The data arrives as monthly files and reports, so I spent the
  time on getting the figures right. The next step would be a scheduler that re-runs the pipeline.
- **A holiday calendar.** None is provided, so every weekday is scheduled (D-25). No US federal holiday
  closes the buildings in the provided month.
- **The payroll week for wage rate effective dates.** The union agreement refers to it but never
  defines it, so the date shown is used (D-27). It only matters in the first days of a rate year.
- **Authentication.** The API and interface have no login, and review decisions are not attributed to
  a person. Every port is bound to 127.0.0.1. Authentication is the first thing to add before anyone
  else uses the system.
- **Editing records from the interface.** The review queue approves, dismisses and acknowledges, but it
  does not correct a record (for example, link an unidentified worker to an employee). Corrections are
  made at the source and picked up by the next run.
- **Automated interface tests and a chatbot eval.** The interface is type-checked and was checked in a
  browser on desktop and phone. The chatbot's SQL guard and tool loop have unit tests that do not call
  the model, but no eval set grades its answers.
