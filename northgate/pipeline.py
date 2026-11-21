"""Pipeline entry point: `python -m northgate.pipeline`.

Runs every step in order against a fresh copy of the source tables. Later steps (resolution,
KPIs, call-outs, payroll, billing, outputs) are added here as they are built.
"""

import calendar
import logging
from datetime import date

from northgate import db, outputs
from northgate.callouts.run import callout_shifts, run_callouts
from northgate.clients import build_clients
from northgate.config import load_settings
from northgate.ingest.run import infer_period, ingest_apis, ingest_files
from northgate.kpis.run import run_kpis
from northgate.llm import build_extractor
from northgate.payroll.writer import write_to_payroll
from northgate.resolve.run import resolve_all

log = logging.getLogger("northgate")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request is too noisy
    settings = load_settings()
    engine = db.connect(settings.database_url)
    db.rebuild_source_tables(engine)

    # Contracts and scanned forms go to the strongest model; call-out messages are short and many,
    # so they use a cheaper one. Both share the answer cache (the model is part of its key).
    extractor = build_extractor(settings.anthropic_api_key, settings.anthropic_model, db.DbCache(engine))
    callout_extractor = build_extractor(
        settings.anthropic_api_key, settings.anthropic_callout_model, db.DbCache(engine)
    )
    if settings.anthropic_api_key is None:
        log.warning("ANTHROPIC_API_KEY not set: documents not already in the cache will be skipped")

    counts = ingest_files(settings.data_dir, engine, extractor)
    period = settings.period or infer_period(engine)
    log.info("Reporting period: %s%s", period, "" if settings.period else " (inferred from punches)")

    payroll, dispatch, finance = build_clients(settings)
    counts += ingest_apis(engine, payroll, dispatch, finance, period)

    counts += resolve_all(engine, period_end(period))
    start, end = period_start(period), period_end(period)

    run_callouts(engine, callout_extractor, start, end)
    write_to_payroll(engine, payroll, settings.payroll_dry_run)
    log.info(
        "wrote payroll_submissions.csv (%d rows)",
        outputs.write_payroll_submissions(engine, settings.output_dir),
    )

    events = db.fetch(engine, db.callout_events)
    run_kpis(
        engine, settings.output_dir, period, start, end, callout_shifts=callout_shifts(events, start, end)
    )

    for table, count in sorted(counts.items()):
        log.info("loaded %-22s %5d rows", table, count)

    written = outputs.write_exceptions(engine, settings.output_dir)
    log.info("wrote exceptions.csv (%d rows)", written)


def period_start(period: str) -> date:
    """'2026-10' -> date(2026, 10, 1)."""
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, 1)


def period_end(period: str) -> date:
    """'2026-10' -> date(2026, 10, 31)."""
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


if __name__ == "__main__":
    main()
