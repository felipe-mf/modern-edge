# Northgate data spine and call-out automation

ModernEdge AI Solutions Engineer assessment. Work in progress.

## Run

1. Start the client systems (payroll, dispatch, finance) from the assessment package:
   `cd mock_systems && docker compose up --build`.
2. Put the client files in `./data` (or point `DATA_DIR` at them) and copy `.env.example` to `.env`
   to set `ANTHROPIC_API_KEY`.
3. `docker compose up --build`. Outputs are written to `./output`.

The pipeline loads every source into Postgres (one table per source, each row with a `source_ref`
back to its file line or API record). Postgres data lives in the `pgdata` volume, so cached document
extractions survive `docker compose down`; `docker compose down -v` starts from zero.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `./data` | Client files, mounted read-only |
| `PAYROLL_URL`, `DISPATCH_URL`, `FINANCE_URL` | `http://host.docker.internal:808{1,2,3}` | Client systems |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | `claude-opus-5-5` | Model used for extraction |
| `PAYROLL_DRY_RUN` | `false` | Decide every absence without writing to payroll |
| `PERIOD` | inferred | Reporting month, `YYYY-MM` |

## Development

```
uv sync
uv run pytest
uv run python -m northgate.smoke   # connectivity check against the client systems
```

See `docs/decisions_log.md` for every conflict resolved and `AI_USAGE.md` for how AI was used.
