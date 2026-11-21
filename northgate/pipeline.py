"""Pipeline entry point: `python -m northgate.pipeline`.

Runs every step in order against a fresh copy of the source tables. Later steps (resolution,
KPIs, call-outs, payroll, billing, outputs) are added here as they are built.
"""

import calendar
import logging
from datetime import date

from northgate import db, outputs
from northgate.clients import build_clients
from northgate.config import load_settings
from northgate.ingest.run import infer_period, ingest_apis, ingest_files
from northgate.llm import build_extractor
from northgate.resolve.run import resolve_all

log = logging.getLogger("northgate")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request is too noisy
    settings = load_settings()
    engine = db.connect(settings.database_url)
    db.rebuild_source_tables(engine)

    extractor = build_extractor(settings.anthropic_api_key, settings.anthropic_model, db.DbCache(engine))
    if settings.anthropic_api_key is None:
        log.warning("ANTHROPIC_API_KEY not set: documents not already in the cache will be skipped")

    counts = ingest_files(settings.data_dir, engine, extractor)
    period = settings.period or infer_period(engine)
    log.info("Reporting period: %s%s", period, "" if settings.period else " (inferred from punches)")

    payroll, dispatch, finance = build_clients(settings)
    counts += ingest_apis(engine, payroll, dispatch, finance, period)

    counts += resolve_all(engine, period_end(period))

    for table, count in sorted(counts.items()):
        log.info("loaded %-22s %5d rows", table, count)

    written = outputs.write_exceptions(engine, settings.output_dir)
    log.info("wrote exceptions.csv (%d rows)", written)


def period_end(period: str) -> date:
    """'2026-10' -> date(2026, 10, 31)."""
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


if __name__ == "__main__":
    main()
