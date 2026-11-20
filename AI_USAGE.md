# AI usage

Where AI tools were used in this project and what I verified myself.

## Tools

- **Claude Code** (Anthropic) as a pair programmer in the terminal.
- **Claude API** inside the system, only to *extract* structured data from free text and scanned
  forms (call-outs, Personnel Action Forms). Every decision that affects pay or billing
  (eligibility, notice, sick balance, absence code, billable amount) is deterministic code.

## Log

| Area | How AI was used | What I verified myself |
|---|---|---|
| Discovery | Read the package documents, profiled every file and API, drafted the map of source conflicts | Checked the conflicts against the raw files and API responses; recomputed sample invoice coverage amounts and one GL week by hand |
| API clients | Generated the HTTP clients (retry, OAuth refresh, pagination, report jobs) | Ran them against the mock systems from the host and from inside Docker Compose; unit tests for retry, token refresh, cursor paging and failed report jobs |
